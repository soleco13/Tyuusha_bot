"""Умная обработка фото: лица (OpenCV), улучшение слабых фото (Real-ESRGAN), вырезание фона (U²-Net-P).

Модели лежат в assets/models и работают на процессоре через onnxruntime:
  realesr-general-x4v3.onnx — Real-ESRGAN, BSD-3 (github.com/xinntao/Real-ESRGAN), собрана из официальных весов;
  u2netp.onnx — U²-Net-P, Apache-2.0 (github.com/xuebinqin/U-2-Net), файл из релизов rembg (MIT).
Если библиотек или моделей нет, всё продолжает работать: кадр по центру, фото без улучшения.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger("photoai")
MODELS = Path(__file__).resolve().parent / "assets" / "models"
DEFAULT_CENTER = (0.5, 0.42)
_lock = threading.Lock()
_cache: dict[str, object] = {}

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


# ---------- лица ----------

def _detector():
    """YuNet из OpenCV (MIT, github.com/opencv/opencv_zoo) — быстрый нейросетевой поиск лиц."""
    if "faces" not in _cache:
        try:
            import cv2
            # модель передаём из памяти: OpenCV на Windows не открывает пути с кириллицей
            model = np.frombuffer((MODELS / "face_detection_yunet_2023mar.onnx").read_bytes(), dtype=np.uint8)
            _cache["faces"] = cv2.FaceDetectorYN.create("onnx", model, np.array([], dtype=np.uint8),
                                                        (320, 320), 0.75, 0.3, 50)
        except Exception as e:  # нет OpenCV или модели — работаем без лиц
            log.warning("Поиск лиц недоступен: %s", e)
            _cache["faces"] = None
    return _cache["faces"]


def detect_faces(img: Image.Image) -> list[tuple[float, float, float, float]]:
    """Лица на фото: (x, y, w, h) в долях от размера, крупные сначала."""
    det = _detector()
    if det is None or np is None:
        return []
    small = img.convert("RGB")
    small.thumbnail((640, 640))
    bgr = np.ascontiguousarray(np.asarray(small)[:, :, ::-1])
    W, H = small.size
    with _lock:
        det.setInputSize((W, H))
        _, found = det.detect(bgr)
    if found is None:
        return []
    boxes = sorted(((max(0, x) / W, max(0, y) / H, w / W, h / H) for x, y, w, h in (f[:4] for f in found)),
                   key=lambda b: -b[2] * b[3])
    if not boxes:
        return []
    big = boxes[0][2] * boxes[0][3]
    return [b for b in boxes if b[2] * b[3] >= big * 0.2][:8]  # мелкие «лица» на фоне — скорее ошибки


def face_box(img: Image.Image) -> tuple[float, float, float, float] | None:
    """Рамка вокруг всех лиц (в долях), считается один раз и запоминается в img.info."""
    if "face_box" in img.info and img.info.get("face_aspect") != round(img.width / img.height, 3):
        del img.info["face_box"]  # картинку повернули или обрезали — ищем заново
    if "face_box" not in img.info:
        img.info["face_aspect"] = round(img.width / img.height, 3)
        faces = detect_faces(img)
        if faces:
            x1 = min(f[0] for f in faces)
            y1 = min(f[1] for f in faces)
            x2 = max(f[0] + f[2] for f in faces)
            y2 = max(f[1] + f[3] for f in faces)
            # голова выше лица и подбородок ниже: немного расширяем рамку
            h = y2 - y1
            img.info["face_box"] = (max(0, x1 - .04), max(0, y1 - h * .35), min(1, x2 + .04), min(1, y2 + h * .15))
        else:
            img.info["face_box"] = None
    return img.info["face_box"]


def centering(size: tuple[int, int], aspect: float, box, default=DEFAULT_CENTER) -> tuple[float, float]:
    """Параметр centering для ImageOps.fit, чтобы рамка лиц была в кадре. Та же формула в Mini App."""
    if not box:
        return default
    W, H = size
    if W / H > aspect:
        crop_w, crop_h = H * aspect, H
    else:
        crop_w, crop_h = W, W / aspect
    cx, cy = (box[0] + box[2]) / 2 * W, (box[1] + box[3]) / 2 * H

    def axis(c, crop, full):
        return 0.5 if full - crop < 1 else min(1.0, max(0.0, (c - crop / 2) / (full - crop)))
    return axis(cx, crop_w, W), axis(cy, crop_h, H)


def face_cut(size: tuple[int, int], aspect: float, box) -> bool:
    """True — лица не помещаются целиком в кадр такой формы (лучше другое фото)."""
    if not box:
        return False
    W, H = size
    crop_w, crop_h = (H * aspect, H) if W / H > aspect else (W, W / aspect)
    return (box[2] - box[0]) * W > crop_w * 1.02 or (box[3] - box[1]) * H > crop_h * 1.02


def fit(photo: Image.Image, size: tuple[int, int], default=DEFAULT_CENTER) -> Image.Image:
    """Как ImageOps.fit, но кадр держит лица в центре."""
    c = centering(photo.size, size[0] / size[1], face_box(photo), default)
    return ImageOps.fit(photo, size, Image.LANCZOS, centering=c)


# ---------- нейросети ----------

def _session(name: str):
    if name not in _cache:
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2  # не забираем весь процессор у бота
            _cache[name] = ort.InferenceSession(str(MODELS / name), opts, providers=["CPUExecutionProvider"])
        except Exception as e:
            log.warning("Модель %s недоступна: %s", name, e)
            _cache[name] = None
    return _cache[name]


def can_enhance() -> bool:
    return np is not None and (MODELS / "realesr-general-x4v3.onnx").exists()


def enhance(img: Image.Image, target_min_side: int = 1500, tile: int = 192, pad: int = 12) -> Image.Image:
    """Увеличивает слабое фото в 2–4 раза нейросетью Real-ESRGAN (по кусочкам, чтобы хватило памяти)."""
    sess = _session("realesr-general-x4v3.onnx")
    if sess is None or min(img.size) >= target_min_side:
        return img
    src = img.convert("RGB")
    limit = 900  # больше вход не нужен: ×4 уже даст 3600 px
    if max(src.size) > limit:
        src.thumbnail((limit, limit), Image.LANCZOS)
    arr = np.asarray(src, dtype=np.float32).transpose(2, 0, 1) / 255.0
    _, H, W = arr.shape
    out = np.zeros((3, H * 4, W * 4), dtype=np.float32)
    for y in range(0, H, tile):
        for x in range(0, W, tile):
            y1, x1 = max(0, y - pad), max(0, x - pad)
            y2, x2 = min(H, y + tile + pad), min(W, x + tile + pad)
            with _lock:
                res = sess.run(None, {"input": arr[None, :, y1:y2, x1:x2]})[0][0]
            oy, ox = (y - y1) * 4, (x - x1) * 4
            h, w = min(tile, H - y) * 4, min(tile, W - x) * 4
            out[:, y * 4:y * 4 + h, x * 4:x * 4 + w] = res[:, oy:oy + h, ox:ox + w]
    result = Image.fromarray((np.clip(out, 0, 1).transpose(1, 2, 0) * 255 + .5).astype(np.uint8))
    scale = target_min_side * 1.6 / min(result.size)
    if scale < 1:  # не раздуваем без нужды
        result = result.resize((round(result.width * scale), round(result.height * scale)), Image.LANCZOS)
    result.info.update({k: v for k, v in img.info.items() if k in ("face_box", "face_aspect")})
    return result


def can_cutout() -> bool:
    return np is not None and (MODELS / "u2netp.onnx").exists()


def cutout_mask(img: Image.Image) -> Image.Image | None:
    """Маска главного объекта (человек, питомец, предмет) — L-изображение того же размера; None, если модели нет."""
    sess = _session("u2netp.onnx")
    if sess is None:
        return None
    src = img.convert("RGB").resize((320, 320), Image.LANCZOS)
    arr = np.asarray(src, dtype=np.float32) / 255.0
    arr = (arr - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
    inp = arr.transpose(2, 0, 1)[None].astype(np.float32)
    with _lock:
        pred = sess.run(None, {sess.get_inputs()[0].name: inp})[0][0, 0]
    pred = (pred - pred.min()) / max(1e-6, pred.max() - pred.min())
    mask = Image.fromarray((pred * 255).astype(np.uint8)).resize(img.size, Image.LANCZOS)
    # убираем полупрозрачную «дымку» по краям, оставляя мягкий край
    return mask.point(lambda v: 0 if v < 40 else 255 if v > 200 else (v - 40) * 255 // 160)
