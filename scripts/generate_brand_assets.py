"""Generate Pine raster and Windows icon assets from the canonical SVG mark."""

from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "ttc3018_control" / "qt" / "assets"
MARK = ASSETS / "pine-mark.svg"


def render_mark(path: Path, size: int) -> None:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(MARK)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    if not image.save(str(path)):
        raise RuntimeError(f"Unable to save {path}")


def render_splash(path: Path) -> None:
    width, height = 960, 540
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor("#181A1F"))
    gradient.setColorAt(1, QColor("#202A36"))
    painter.fillRect(image.rect(), gradient)

    renderer = QSvgRenderer(str(MARK))
    renderer.render(painter, QRectF(372, 70, 216, 216))

    painter.setPen(QColor("#F2F4F7"))
    title_font = QFont("Segoe UI", 46, QFont.DemiBold)
    title_font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
    painter.setFont(title_font)
    painter.drawText(QRectF(0, 305, width, 70), Qt.AlignHCenter | Qt.AlignVCenter, "PINE")

    painter.setPen(QColor("#63B8FF"))
    label_font = QFont("Segoe UI", 12, QFont.DemiBold)
    label_font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
    painter.setFont(label_font)
    painter.drawText(QRectF(0, 378, width, 32), Qt.AlignHCenter | Qt.AlignVCenter, "CNC STUDIO")

    painter.setPen(QColor("#737B87"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(QRectF(0, 475, width, 25), Qt.AlignHCenter | Qt.AlignVCenter, "Preparing your workspace")
    painter.end()
    if not image.save(str(path)):
        raise RuntimeError(f"Unable to save {path}")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    render_mark(ASSETS / "pine-mark.png", 1024)
    render_splash(ASSETS / "pine-splash.png")
    with Image.open(ASSETS / "pine-mark.png") as source:
        source.save(
            ASSETS / "pine.ico",
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    app.quit()


if __name__ == "__main__":
    main()
