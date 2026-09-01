from __future__ import annotations

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QSplashScreen

from ..application.controller import ApplicationController
from .view_model import ControllerViewModel


QML_ROOT = Path(__file__).with_name("qml")
ASSET_ROOT = Path(__file__).with_name("assets")
_STYLE_INITIALIZED = False


def _configure_logging(root: Path) -> logging.Logger:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "pine.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
    logger = logging.getLogger("pine")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False

    def log_exception(exc_type, exc_value, exc_traceback) -> None:
        logger.critical("Unhandled application exception", exc_info=(exc_type, exc_value, exc_traceback))

    def log_thread_exception(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled thread exception in %s",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception
    logger.info("Pine starting")
    return logger


def build_engine(*, visible: bool = True, auto_connect: bool = False) -> tuple[QQmlApplicationEngine, ControllerViewModel]:
    """Load the Qt shell without starting the Qt event loop; useful for checks."""
    global _STYLE_INITIALIZED
    if not _STYLE_INITIALIZED:
        QQuickStyle.setStyle("Basic")
        _STYLE_INITIALIZED = True
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("Create QGuiApplication before loading the Pine Qt shell")
    engine = QQmlApplicationEngine()
    logger = logging.getLogger("pine.qt")
    engine.warnings.connect(lambda warnings: [logger.warning(warning.toString()) for warning in warnings])
    application = ApplicationController(Path.cwd())
    view_model = ControllerViewModel(application, auto_connect=auto_connect)
    # The context property does not transfer Python ownership; retain it with
    # the engine for the full QML lifecycle.
    engine._ttc3018_view_model = view_model  # type: ignore[attr-defined]
    engine.rootContext().setContextProperty("appViewModel", view_model)
    engine.rootContext().setContextProperty("startupWindowVisible", visible)
    engine.addImportPath(str(QML_ROOT))
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("Unable to load Pine Qt shell")
    return engine, view_model


def main() -> None:
    logger = _configure_logging(Path.cwd())
    if "--check" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName("Pine")
    app.setApplicationDisplayName("Pine")
    app.setOrganizationName("Pine CNC")
    app.setWindowIcon(QIcon(str(ASSET_ROOT / "pine.ico")))
    if "--check" in sys.argv:
        engine, view_model = build_engine()
        print("Pine Qt shell check passed")
        engine.deleteLater()
        return
    splash = QSplashScreen(QPixmap(str(ASSET_ROOT / "pine-splash.png")))
    splash.show()
    app.processEvents()
    engine, view_model = build_engine(visible=False, auto_connect=True)
    root = engine.rootObjects()[0]

    def reveal_workspace() -> None:
        root.show()
        splash.close()

    QTimer.singleShot(550, reveal_workspace)
    app.aboutToQuit.connect(view_model.close)
    app.aboutToQuit.connect(lambda: logger.info("Pine stopped cleanly"))
    sys.exit(app.exec())
