from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..application.controller import ApplicationController
from .view_model import ControllerViewModel


QML_ROOT = Path(__file__).with_name("qml")
_STYLE_INITIALIZED = False


def build_engine() -> tuple[QQmlApplicationEngine, ControllerViewModel]:
    """Load the Qt shell without starting the Qt event loop; useful for checks."""
    global _STYLE_INITIALIZED
    if not _STYLE_INITIALIZED:
        QQuickStyle.setStyle("Basic")
        _STYLE_INITIALIZED = True
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("Create QGuiApplication before loading the TTC 3018 Qt shell")
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [print(warning.toString(), file=sys.stderr) for warning in warnings])
    application = ApplicationController(Path.cwd())
    view_model = ControllerViewModel(application)
    # The context property does not transfer Python ownership; retain it with
    # the engine for the full QML lifecycle.
    engine._ttc3018_view_model = view_model  # type: ignore[attr-defined]
    engine.rootContext().setContextProperty("appViewModel", view_model)
    engine.addImportPath(str(QML_ROOT))
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("Unable to load TTC 3018 Qt shell")
    return engine, view_model


def main() -> None:
    if "--check" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv)
    engine, view_model = build_engine()
    if "--check" in sys.argv:
        print("TTC 3018 Qt shell check passed")
        engine.deleteLater()
        return
    app.aboutToQuit.connect(view_model.close)
    sys.exit(app.exec())
