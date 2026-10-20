# Модели для photoai.py

Работают на процессоре через onnxruntime, интернет не нужен.

| Файл | Что делает | Лицензия и источник |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | находит лица, чтобы кадр держал их в центре | MIT, [opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| `realesr-general-x4v3.onnx` | улучшает слабые фото (×4) | BSD-3, [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN); собрана из официальных весов `realesr-general-x4v3.pth` |
| `u2netp.onnx` | вырезает фон для наклеек | Apache-2.0, [U²-Net](https://github.com/xuebinqin/U-2-Net); файл из релизов [rembg](https://github.com/danielgatis/rembg) |
