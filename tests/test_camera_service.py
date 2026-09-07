from __future__ import annotations

from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame

from ttc3018_control.live.frames import FrameHub
from ttc3018_control.qt.camera_service import CameraService


def test_camera_frame_is_scaled_encoded_and_published(qapp) -> None:
    hub = FrameHub()
    camera = CameraService(hub)
    camera.frame_interval = 0
    camera._set_state("starting")

    image = QImage(16, 12, QImage.Format.Format_RGB888)
    image.fill(0x336699)
    camera._on_frame(QVideoFrame(image))

    assert qapp is not None
    assert camera.state == "ready"
    assert hub.latest().jpeg.startswith(b"\xff\xd8")
