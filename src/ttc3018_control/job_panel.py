from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import TYPE_CHECKING

from .gcode import GCodeError, GCodeProgram, load_gcode

if TYPE_CHECKING:
    from .app import ControllerApp


class JobPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: ControllerApp) -> None:
        super().__init__(parent, text="4. Create, preview, and run a job", style="Section.TLabelframe")
        self.app = app
        self.program: GCodeProgram | None = None
        self.file_var = tk.StringVar(value="No G-code loaded")
        self.summary_var = tk.StringVar(value="Load a metric, pre-sliced engraving file.")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text_var = tk.StringVar(value="Idle")
        self.rpm_var = tk.IntVar(value=1000)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        source_buttons = ttk.Frame(self)
        source_buttons.grid(row=0, column=0, sticky="ew")
        for column in range(3):
            source_buttons.columnconfigure(column, weight=1)
        ttk.Button(source_buttons, text="Load G-code…", command=self.load, style="Soft.TButton").grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        ttk.Button(source_buttons, text="Create Text…", command=app.open_text_engraver, style="Soft.TButton").grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )
        ttk.Button(source_buttons, text="Create Plaque…", command=app.open_plaque_engraver, style="SoftAccent.TButton").grid(
            row=0, column=2, sticky="ew", padx=(3, 0)
        )
        ttk.Label(self, textvariable=self.file_var, wraplength=430).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(self, textvariable=self.summary_var, wraplength=430).grid(row=2, column=0, sticky="w", pady=(4, 8))

        self.preview = tk.Canvas(self, background="#101820", highlightthickness=1, highlightbackground="#64727d")
        self.preview.grid(row=3, column=0, sticky="nsew")
        self.preview.bind("<Configure>", lambda _event: self.draw_preview())

        spindle = ttk.Frame(self)
        spindle.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(spindle, text="Spindle RPM").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(spindle, from_=1, to=24000, textvariable=self.rpm_var, width=9).grid(row=0, column=1, padx=6)
        self.spindle_start = ttk.Button(spindle, text="Start spindle…", command=app.start_spindle, style="SoftAccent.TButton")
        self.spindle_start.grid(row=0, column=2, padx=3)
        self.spindle_stop = ttk.Button(spindle, text="Stop spindle", command=app.stop_spindle, style="SoftDanger.TButton")
        self.spindle_stop.grid(row=0, column=3, padx=3)

        ttk.Progressbar(self, variable=self.progress_var, maximum=100).grid(row=5, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(self, textvariable=self.progress_text_var).grid(row=6, column=0, sticky="w")

        controls = ttk.Frame(self)
        controls.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        for column in range(4):
            controls.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(controls, text="Start job…", command=app.start_job, style="SoftAccent.TButton")
        self.pause_button = ttk.Button(controls, text="Pause", command=app.pause_job, style="Soft.TButton")
        self.resume_button = ttk.Button(controls, text="Resume", command=app.resume_job, style="Soft.TButton")
        self.abort_button = ttk.Button(controls, text="Abort…", command=app.abort_job, style="SoftDanger.TButton")
        for column, button in enumerate((self.start_button, self.pause_button, self.resume_button, self.abort_button)):
            button.grid(row=0, column=column, sticky="ew", padx=2)
        self.update_controls()

    def load(self) -> None:
        if self.app.job_active:
            self.app._set_action_status("G-code load ignored — finish or abort the active job first")
            return
        selected = filedialog.askopenfilename(
            parent=self,
            title="Load pre-sliced G-code",
            filetypes=(("G-code", "*.nc *.gcode *.tap *.cnc *.txt"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            program = load_gcode(Path(selected))
        except (OSError, GCodeError) as exc:
            messagebox.showerror("G-code rejected", str(exc), parent=self)
            return
        self.set_program(program)

    def set_program(self, program: GCodeProgram) -> None:
        if self.app.job_active:
            raise RuntimeError("Abort or finish the current job before replacing its G-code")
        self.program = program
        if self.app.setup_wizard is not None and self.app.setup_wizard.winfo_exists():
            self.app.setup_wizard.reset_job_confirmations()
        bounds = program.bounds
        size = bounds.size
        spindle_start = next(
            (command for command in program.commands if command.split(maxsplit=1)[0] in {"M3", "M4"}),
            None,
        )
        spindle_note = f"spindle start: {spindle_start}" if spindle_start else "no spindle-start command"
        self.file_var.set(program.path.name)
        self.summary_var.set(
            f"{len(program.commands)} commands; X {bounds.minimum.x:.3f}…{bounds.maximum.x:.3f}, "
            f"Y {bounds.minimum.y:.3f}…{bounds.maximum.y:.3f}, Z {bounds.minimum.z:.3f}…{bounds.maximum.z:.3f} mm "
            f"(size {size.x:.3f} × {size.y:.3f} mm); {spindle_note}"
        )
        self.progress_var.set(0)
        self.progress_text_var.set("Loaded — establish machine reference and work zero before starting")
        self.draw_preview()
        self.update_controls()

    def draw_preview(self) -> None:
        canvas = self.preview
        canvas.delete("all")
        width = max(canvas.winfo_width(), 100)
        height = max(canvas.winfo_height(), 100)
        margin = 18
        if self.program is None:
            canvas.create_text(width / 2, height / 2, text="Toolpath preview", fill="#9eb1bd")
            return
        bounds = self.program.bounds
        span_x = max(bounds.maximum.x - bounds.minimum.x, 0.001)
        span_y = max(bounds.maximum.y - bounds.minimum.y, 0.001)
        scale = min((width - margin * 2) / span_x, (height - margin * 2) / span_y)

        def xy(x: float, y: float) -> tuple[float, float]:
            return (
                margin + (x - bounds.minimum.x) * scale,
                height - margin - (y - bounds.minimum.y) * scale,
            )

        for segment in self.program.segments:
            start = xy(segment.start.x, segment.start.y)
            end = xy(segment.end.x, segment.end.y)
            canvas.create_line(*start, *end, fill="#657580" if segment.rapid else "#34d399", width=1)
        origin = xy(0, 0)
        canvas.create_line(origin[0] - 5, origin[1], origin[0] + 5, origin[1], fill="#ffbf69")
        canvas.create_line(origin[0], origin[1] - 5, origin[0], origin[1] + 5, fill="#ffbf69")

    def update_progress(self) -> None:
        job = self.app.job
        self.progress_var.set(job.progress * 100)
        if job.total:
            self.progress_text_var.set(f"{job.state.title()} — {job.completed} / {job.total} commands")
        else:
            self.progress_text_var.set(job.state.title())
        self.update_controls()

    def update_controls(self) -> None:
        state = self.app.job.state
        connected = self.app.connection.connected
        self.start_button.configure(state="normal" if self.program and connected and state not in {"running", "paused"} else "disabled")
        self.pause_button.configure(state="normal" if state == "running" else "disabled")
        self.resume_button.configure(state="normal" if state == "paused" else "disabled")
        self.abort_button.configure(state="normal" if state in {"running", "paused"} else "disabled")
        self.spindle_start.configure(state="normal" if connected and not self.app.job_active else "disabled")
        self.spindle_stop.configure(state="normal" if connected else "disabled")
