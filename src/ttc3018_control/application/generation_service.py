"""Qt-independent orchestration for text, plaque, and STEP generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plaque_engraver import generate_plaque_gcode
from ..step_engraver import generate_step_gcode
from ..step_geometry import StepPlanarModel, load_step_isolated
from ..text_engraver import generate_text_gcode


@dataclass(frozen=True)
class GeneratedArtifact:
    """Generated output plus the metadata needed by any presentation adapter."""

    kind: str
    filename: str
    result: Any

    @property
    def gcode(self) -> str:
        return self.result.gcode

    @property
    def strokes(self):
        return self.result.strokes


class GenerationService:
    """Keep generator selection and output naming outside the Qt adapter."""

    def text(self, *args, **kwargs) -> GeneratedArtifact:
        return GeneratedArtifact("Text", "generated-text.gcode", generate_text_gcode(*args, **kwargs))

    def plaque(self, *args, **kwargs) -> GeneratedArtifact:
        return GeneratedArtifact("Plaque", "generated-plaque.gcode", generate_plaque_gcode(*args, **kwargs))

    def step(self, model: StepPlanarModel, *args, **kwargs) -> GeneratedArtifact:
        return GeneratedArtifact("STEP", "generated-step.gcode", generate_step_gcode(model, *args, **kwargs))

    def import_step(self, path, plane: str | None = None) -> StepPlanarModel:
        """Keep native STEP loading behind the application generation boundary."""
        return load_step_isolated(path, plane)
