from __future__ import annotations

import argparse
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
from ..backend.process import BackendProcessManager
from ..backend.discovery import default_data_root
from ..backend.data_migration import assert_data_root_not_migrating
from ..backend.qt_adapter import BackendApplicationAdapter
from .view_model import ControllerViewModel


QML_ROOT = Path(__file__).with_name("qml")
ASSET_ROOT = Path(__file__).with_name("assets")
PINE_ICON = ASSET_ROOT / "pine.ico"
WINDOWS_APP_USER_MODEL_ID = "Pine.CNCStudio"
_STYLE_INITIALIZED = False


def _configure_windows_identity() -> None:
    """Give unpackaged Pine launches their own Windows taskbar identity."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        logging.getLogger("pine.qt").warning("Unable to set the Windows application identity")


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


def build_engine(*, visible: bool = True, auto_connect: bool = False,
                 application: ApplicationController | None = None,
                 backend_client=None, root: Path | None = None) -> tuple[QQmlApplicationEngine, ControllerViewModel]:
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
    if application is not None and backend_client is not None:
        raise ValueError("Choose an in-process application or a backend client, not both")
    application_root = getattr(application, "root", None) if application is not None else None
    data_root = default_data_root(root if root is not None else application_root)
    controller = application or (BackendApplicationAdapter(backend_client, data_root)
                                 if backend_client is not None else ApplicationController(data_root))
    view_model = ControllerViewModel(controller, auto_connect=auto_connect, root=data_root)
    # The context property does not transfer Python ownership; retain it with
    # the engine for the full QML lifecycle.
    engine._ttc3018_view_model = view_model  # type: ignore[attr-defined]
    engine.rootContext().setContextProperty("appViewModel", view_model)
    engine.rootContext().setContextProperty("startupWindowVisible", visible)
    engine.addImportPath(str(QML_ROOT))
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("Unable to load Pine Qt shell")
    engine.rootObjects()[0].setIcon(QIcon(str(PINE_ICON)))
    return engine, view_model


def parse_startup_arguments(argv: list[str] | None = None) -> tuple[Path | None, bool, list[str]]:
    """Return the explicit data root, check mode, and arguments for Qt."""
    parser = argparse.ArgumentParser(prog="pine-cnc", allow_abbrev=False)
    parser.add_argument("--data-root", "--root", dest="data_root", type=Path,
                        help="use this application data root (default: launch working directory)")
    parser.add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    options, qt_arguments = parser.parse_known_args(argv)
    return options.data_root, options.check, qt_arguments


def main(argv: list[str] | None = None) -> None:
    data_root_argument, check_mode, qt_arguments = parse_startup_arguments(
        list(sys.argv[1:] if argv is None else argv)
    )
    data_root = default_data_root(data_root_argument)
    assert_data_root_not_migrating(data_root)
    logger = _configure_logging(data_root)
    if check_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _configure_windows_identity()
    app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName("Pine")
    app.setApplicationDisplayName("Pine")
    app.setOrganizationName("Pine CNC")
    pine_icon = QIcon(str(PINE_ICON))
    app.setWindowIcon(pine_icon)
    if check_mode:
        manager = BackendProcessManager(data_root)
        backend_client = manager.attach_or_spawn()
        engine, view_model = build_engine(backend_client=backend_client, root=data_root)
        print("Pine Qt shell check passed")
        view_model.close()
        manager.close_client()
        engine.deleteLater()
        return
    splash = QSplashScreen(QPixmap(str(ASSET_ROOT / "pine-splash.png")))
    splash.show()
    app.processEvents()
    manager = BackendProcessManager(data_root)
    backend_client = manager.attach_or_spawn()
    engine, view_model = build_engine(visible=False, auto_connect=True,
                                      backend_client=backend_client, root=data_root)
    root = engine.rootObjects()[0]

    def reveal_workspace() -> None:
        root.show()
        splash.close()

    QTimer.singleShot(550, reveal_workspace)
    app.aboutToQuit.connect(view_model.close)
    app.aboutToQuit.connect(manager.close_client)
    app.aboutToQuit.connect(lambda: logger.info("Pine stopped cleanly"))
    sys.exit(app.exec())
