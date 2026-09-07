"""Single Qt Multimedia camera pipeline shared by Pine and Pine Live."""

from __future__ import annotations

import base64
import time
from PySide6.QtCore import QByteArray, QObject, QBuffer, QIODevice, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoFrame, QVideoSink

from ..live.frames import FrameHub


class CameraService(QObject):
    state_changed = Signal(str)
    camera_list_changed = Signal()
    frame_changed = Signal()
    frame_data_changed = Signal(str)

    def __init__(self, frame_hub: FrameHub, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.frames = frame_hub
        self._devices = list(QMediaDevices.videoInputs())
        self._camera: QCamera | None = None
        self._sink = QVideoSink(self)
        self._session = QMediaCaptureSession(self)
        self._session.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._selected_id = ""
        self._state = "off"
        self._running = False
        self._last_encoded_at = 0.0
        self.frame_interval = 1.0

    @property
    def state(self) -> str:
        return self._state

    @property
    def devices(self):
        return tuple(self._devices)

    @property
    def device_names(self) -> list[str]:
        return [device.description() for device in self._devices]

    @property
    def sink(self) -> QVideoSink:
        return self._sink

    def refresh(self) -> None:
        self._devices = list(QMediaDevices.videoInputs())
        self.camera_list_changed.emit()

    @Slot(str)
    def select(self, device_id: str) -> None:
        self._selected_id = device_id
        if self._running:
            self.stop()
            self.start()

    @Slot()
    def start(self) -> None:
        if self._running:
            return
        self.refresh()
        device = next((item for item in self._devices if bytes(item.id()).hex() == self._selected_id), None)
        if device is None:
            device = self._devices[0] if self._devices else None
        if device is None:
            self._set_state("unavailable")
            return
        try:
            self._camera = QCamera(device, self)
            self._session.setCamera(self._camera)
            self._camera.errorOccurred.connect(lambda _error, message: self._set_state("error"))
            self._camera.start()
            self._selected_id = bytes(device.id()).hex()
            self._running = True
            self._set_state("starting")
        except Exception:
            self._camera = None
            self._running = False
            self._set_state("error")

    @Slot()
    def stop(self) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._session.setCamera(None)
            self._camera.deleteLater()
            self._camera = None
        self._running = False
        self._set_state("off")

    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state)

    @Slot(QVideoFrame)
    def _on_frame(self, frame: QVideoFrame) -> None:
        now = time.monotonic()
        if now - self._last_encoded_at < self.frame_interval:
            return
        self._last_encoded_at = now
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        image = image.convertToFormat(QImage.Format_RGB888).scaled(
            960,
            540,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        output = QByteArray()
        buffer = QBuffer(output)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if image.save(buffer, "JPEG", 75):
            jpeg = bytes(output)
            self.frames.publish(jpeg)
            if self._state == "starting":
                self._set_state("ready")
            self.frame_changed.emit()
            self.frame_data_changed.emit("data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"))
