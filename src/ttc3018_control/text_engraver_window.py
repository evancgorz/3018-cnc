from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .gcode import parse_gcode
from .text_engraver import FONT_NAMES, TextEngraving, generate_text_gcode

if TYPE_CHECKING:
    from .app import ControllerApp


class TextEngraverWindow(tk.Toplevel):
    def __init__(self, app: ControllerApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("Text Engraver")
        self.geometry("780x840")
        self.minsize(620, 650)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.font_var = tk.StringVar(value="Simple")
        self.height_var = tk.DoubleVar(value=8.0)
        self.depth_var = tk.DoubleVar(value=-0.3)
        self.safe_z_var = tk.DoubleVar(value=3.0)
        self.cut_feed_var = tk.DoubleVar(value=300.0)
        self.plunge_feed_var = tk.DoubleVar(value=100.0)
        self.letter_spacing_var = tk.DoubleVar(value=0.18)
        self.line_spacing_var = tk.DoubleVar(value=1.4)
        self.alignment_var = tk.StringVar(value="Left")
        self.start_spindle_var = tk.BooleanVar(value=False)
        self.spindle_rpm_var = tk.IntVar(value=1000)
        self.summary_var = tk.StringVar(value="Enter text and generate a centerline engraving program.")
        self._preview_engraving: TextEngraving | None = None
        self._preview_after: str | None = None

        shell = ttk.Frame(self, padding=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(2, weight=1)

        ttk.Label(shell, text="Create text engraving", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            shell,
            text=(
                "Bundled single-line fonts generate efficient centerline toolpaths. Text height is a physical millimeter value. "
                "Generated programs leave the spindle off and use the current GRBL work zero."
            ),
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 10))

        text_frame = ttk.LabelFrame(shell, text="Text", padding=8)
        text_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.text = tk.Text(text_frame, height=4, wrap="word", font=("Segoe UI", 12))
        self.text.grid(row=0, column=0, sticky="nsew")
        self.text.insert("1.0", "HELLO")

        settings = ttk.LabelFrame(shell, text="Engraving settings", padding=10)
        settings.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        settings.columnconfigure(1, weight=1)
        rows: list[tuple[str, tk.Variable, tuple[object, ...] | None]] = [
            ("Stroke font", self.font_var, FONT_NAMES),
            ("Text height (mm)", self.height_var, None),
            ("Engraving depth (mm)", self.depth_var, None),
            ("Safe Z above work zero (mm)", self.safe_z_var, None),
            ("Cut feed (mm/min)", self.cut_feed_var, None),
            ("Plunge feed (mm/min)", self.plunge_feed_var, None),
            ("Letter spacing (height ratio)", self.letter_spacing_var, None),
            ("Line spacing (height ratio)", self.line_spacing_var, None),
            ("Alignment", self.alignment_var, ("Left", "Center", "Right")),
        ]
        for row, (label, variable, values) in enumerate(rows):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            if values is not None:
                control = ttk.Combobox(settings, textvariable=variable, values=values, state="readonly")
            else:
                control = ttk.Entry(settings, textvariable=variable)
            control.grid(row=row, column=1, sticky="ew", pady=3)

        spindle_row = len(rows)
        ttk.Checkbutton(
            settings,
            text="Start spindle in generated job (M3)",
            variable=self.start_spindle_var,
        ).grid(row=spindle_row, column=0, sticky="w", pady=3)
        rpm = ttk.Frame(settings)
        rpm.grid(row=spindle_row, column=1, sticky="ew", pady=3)
        ttk.Label(rpm, text="RPM").pack(side="left")
        ttk.Spinbox(rpm, from_=1, to=24000, textvariable=self.spindle_rpm_var, width=10).pack(side="left", padx=8)
        ttk.Label(
            settings,
            text="Leave unchecked for an air cut or when starting the spindle manually in the Job panel.",
            foreground="#555555",
            wraplength=550,
        ).grid(row=spindle_row + 1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        preview = ttk.LabelFrame(shell, text="Live toolpath preview", padding=8)
        preview.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        preview.rowconfigure(0, weight=1)
        preview.columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(preview, background="white", height=190, highlightthickness=1, highlightbackground="#b8b8b8")
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._draw_preview())

        ttk.Label(shell, textvariable=self.summary_var, wraplength=600).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        buttons = ttk.Frame(shell)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        ttk.Button(buttons, text="Cancel", command=self.close).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Button(buttons, text="Save G-code…", command=self.save).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(buttons, text="Generate and Load", command=self.generate_and_load).grid(
            row=0, column=2, sticky="ew", padx=3
        )
        self.text.bind("<KeyRelease>", lambda _event: self._schedule_preview())
        for variable in (
            self.font_var,
            self.height_var,
            self.depth_var,
            self.safe_z_var,
            self.cut_feed_var,
            self.plunge_feed_var,
            self.letter_spacing_var,
            self.line_spacing_var,
            self.alignment_var,
        ):
            variable.trace_add("write", lambda *_args: self._schedule_preview())
        self.after_idle(self._refresh_preview)
        self.text.focus_set()

    def _make_engraving(self) -> TextEngraving:
        return generate_text_gcode(
            self.text.get("1.0", "end-1c"),
            font=self.font_var.get(),
            text_height=float(self.height_var.get()),
            depth=float(self.depth_var.get()),
            safe_z=float(self.safe_z_var.get()),
            cut_feed=float(self.cut_feed_var.get()),
            plunge_feed=float(self.plunge_feed_var.get()),
            letter_spacing=float(self.letter_spacing_var.get()),
            line_spacing=float(self.line_spacing_var.get()),
            alignment=self.alignment_var.get(),
            spindle_rpm=int(self.spindle_rpm_var.get()) if self.start_spindle_var.get() else None,
        )

    def _generate(self) -> TextEngraving | None:
        try:
            engraving = self._make_engraving()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Text engraving not generated", str(exc), parent=self)
            return None
        self.summary_var.set(
            f"Generated size: {engraving.width:.3f} × {engraving.height:.3f} mm; "
            f"{engraving.stroke_count} cutting strokes."
        )
        return engraving

    def _schedule_preview(self) -> None:
        if self._preview_after is not None:
            self.after_cancel(self._preview_after)
        self._preview_after = self.after(80, self._refresh_preview)

    def _refresh_preview(self) -> None:
        self._preview_after = None
        try:
            self._preview_engraving = self._make_engraving()
        except (ValueError, tk.TclError) as exc:
            self._preview_engraving = None
            self.summary_var.set(f"Preview needs a valid setting: {exc}")
        else:
            engraving = self._preview_engraving
            self.summary_var.set(
                f"Preview size: {engraving.width:.3f} × {engraving.height:.3f} mm; "
                f"{engraving.stroke_count} cutting strokes."
            )
        self._draw_preview()

    def _draw_preview(self) -> None:
        canvas = self.preview_canvas
        canvas.delete("all")
        engraving = self._preview_engraving
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if engraving is None:
            canvas.create_text(width / 2, height / 2, text="Enter valid text and settings to preview", fill="#666666")
            return
        padding = 18
        scale = min((width - 2 * padding) / max(engraving.width, 0.1), (height - 2 * padding) / max(engraving.height, 0.1))
        draw_width = engraving.width * scale
        draw_height = engraving.height * scale
        origin_x = (width - draw_width) / 2
        origin_y = (height + draw_height) / 2
        for stroke in engraving.strokes:
            points: list[float] = []
            for x, y in stroke:
                points.extend((origin_x + x * scale, origin_y - y * scale))
            if len(points) >= 4:
                canvas.create_line(*points, fill="#146eb4", width=2, capstyle="round", joinstyle="round")
        canvas.create_rectangle(origin_x, origin_y - draw_height, origin_x + draw_width, origin_y, outline="#b8d6ec")

    def generate_and_load(self) -> None:
        engraving = self._generate()
        if engraving is None:
            return
        path = Path("generated-text.gcode")
        program = parse_gcode(engraving.gcode, path)
        self.app.job_panel.set_program(program)
        self.app._append_system_log(
            f"Generated text engraving loaded: {engraving.width:.3f} x {engraving.height:.3f} mm"
        )
        self.close()

    def save(self) -> None:
        engraving = self._generate()
        if engraving is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Save generated text G-code",
            defaultextension=".gcode",
            initialfile="text-engraving.gcode",
            filetypes=(("G-code", "*.gcode"), ("NC program", "*.nc"), ("All files", "*.*")),
        )
        if not selected:
            return
        path = Path(selected)
        try:
            path.write_text(engraving.gcode, encoding="ascii")
            program = parse_gcode(engraving.gcode, path)
        except OSError as exc:
            messagebox.showerror("G-code not saved", str(exc), parent=self)
            return
        self.app.job_panel.set_program(program)
        self.app._append_system_log(f"Generated text engraving saved and loaded: {path}")
        messagebox.showinfo("Text G-code saved", f"Saved and loaded:\n\n{path}", parent=self)

    def close(self) -> None:
        self.app.text_engraver_window = None
        self.destroy()
