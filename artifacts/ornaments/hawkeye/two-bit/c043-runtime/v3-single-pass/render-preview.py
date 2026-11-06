import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

here = Path(__file__).resolve().parent
source = here / "detail-preview-vbit30-single-pass.svg"
target = here / "detail-preview-vbit30-single-pass.png"
app = QGuiApplication([])
renderer = QSvgRenderer(str(source))
if not renderer.isValid():
    raise SystemExit(f"Invalid SVG: {source}")
image = QImage(1100, 1260, QImage.Format.Format_ARGB32_Premultiplied)
image.fill(0xFFFFFFFF)
painter = QPainter(image)
renderer.render(painter)
painter.end()
if not image.save(str(target)):
    raise SystemExit(f"Failed to write: {target}")
print(target)
