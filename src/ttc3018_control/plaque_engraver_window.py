from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .gcode import parse_gcode
from .plaque_engraver import BORDER_STYLES, PlaqueEngraving, generate_plaque_gcode
from .text_engraver import FONT_NAMES

if TYPE_CHECKING:
    from .app import ControllerApp


class PlaqueEngraverWindow(tk.Toplevel):
    def __init__(self, app: ControllerApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("Plaque Builder")
        self.geometry("820x850")
        self.minsize(650, 680)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.title_var, self.subtitle_var = tk.StringVar(value="WELCOME"), tk.StringVar(value="")
        self.subtitle_enabled_var = tk.BooleanVar(value=False)
        self.title_font_var, self.subtitle_font_var = tk.StringVar(value="Script"), tk.StringVar(value="Simple")
        self.title_height_var, self.subtitle_height_var = tk.DoubleVar(value=12), tk.DoubleVar(value=6)
        self.width_var, self.height_var, self.margin_var = tk.DoubleVar(value=100), tk.DoubleVar(value=50), tk.DoubleVar(value=5)
        self.border_var = tk.StringVar(value="Rounded rectangle")
        self.depth_var, self.safe_z_var = tk.DoubleVar(value=-0.3), tk.DoubleVar(value=3)
        self.cut_feed_var, self.plunge_feed_var = tk.DoubleVar(value=300), tk.DoubleVar(value=100)
        self.start_spindle_var, self.spindle_rpm_var = tk.BooleanVar(value=False), tk.IntVar(value=1000)
        self.summary_var = tk.StringVar(value="Configure a plaque to preview its exact centerline toolpath.")
        self._preview: PlaqueEngraving | None = None
        self._preview_after: str | None = None

        shell = ttk.Frame(self, padding=14)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        ttk.Label(shell, text="Plaque Builder", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(shell, text="Plaque lower-left is work X0 Y0. Border, title, and subtitle share the same cutting settings.", wraplength=740).grid(row=1, column=0, sticky="w", pady=(4, 8))
        text = ttk.LabelFrame(shell, text="Text", padding=8)
        text.grid(row=2, column=0, sticky="ew")
        text.columnconfigure(1, weight=1)
        ttk.Label(text, text="Title").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(text, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(text, text="Include subtitle", variable=self.subtitle_enabled_var, command=self._update_subtitle_state).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.subtitle_entry = ttk.Entry(text, textvariable=self.subtitle_var)
        self.subtitle_entry.grid(row=1, column=1, sticky="ew", pady=3)

        settings = ttk.LabelFrame(shell, text="Layout and engraving settings", padding=8)
        settings.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        settings.columnconfigure(1, weight=1)
        rows = [
            ("Title font", self.title_font_var, FONT_NAMES), ("Title height (mm)", self.title_height_var, None),
            ("Subtitle font", self.subtitle_font_var, FONT_NAMES), ("Subtitle height (mm)", self.subtitle_height_var, None),
            ("Plaque width (mm)", self.width_var, None), ("Plaque height (mm)", self.height_var, None),
            ("Inner margin (mm)", self.margin_var, None), ("Border", self.border_var, BORDER_STYLES),
            ("Depth (mm)", self.depth_var, None), ("Safe Z (mm)", self.safe_z_var, None),
            ("Cut feed (mm/min)", self.cut_feed_var, None), ("Plunge feed (mm/min)", self.plunge_feed_var, None),
        ]
        for row, (label, var, values) in enumerate(rows):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            control = ttk.Combobox(settings, textvariable=var, values=values, state="readonly") if values else ttk.Entry(settings, textvariable=var)
            control.grid(row=row, column=1, sticky="ew", pady=2)
        spindle = ttk.Frame(settings)
        spindle.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(spindle, text="Start spindle in generated job (M3)", variable=self.start_spindle_var).pack(side="left")
        ttk.Label(spindle, text="RPM").pack(side="left", padx=(16, 4))
        ttk.Spinbox(spindle, from_=1, to=24000, textvariable=self.spindle_rpm_var, width=9).pack(side="left")

        preview = ttk.LabelFrame(shell, text="Live toolpath preview", padding=8)
        preview.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        shell.rowconfigure(4, weight=1)
        preview.rowconfigure(0, weight=1); preview.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(preview, background="white", height=220, highlightthickness=1, highlightbackground="#b8b8b8")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        ttk.Label(shell, textvariable=self.summary_var, wraplength=740).grid(row=5, column=0, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(shell); buttons.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        for column in range(3): buttons.columnconfigure(column, weight=1)
        ttk.Button(buttons, text="Cancel", command=self.close).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(buttons, text="Save G-code…", command=self.save).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(buttons, text="Generate and Load", command=self.generate_and_load).grid(row=0, column=2, sticky="ew", padx=2)
        for var in (self.title_var, self.subtitle_var, self.subtitle_enabled_var, self.title_font_var, self.subtitle_font_var, self.title_height_var, self.subtitle_height_var, self.width_var, self.height_var, self.margin_var, self.border_var, self.depth_var, self.safe_z_var, self.cut_feed_var, self.plunge_feed_var):
            var.trace_add("write", lambda *_: self._schedule_preview())
        self._update_subtitle_state()
        self.after_idle(self._refresh_preview)

    def _make(self) -> PlaqueEngraving:
        return generate_plaque_gcode(self.title_var.get(), self.subtitle_var.get(), subtitle_enabled=self.subtitle_enabled_var.get(), title_font=self.title_font_var.get(), subtitle_font=self.subtitle_font_var.get(), title_height=float(self.title_height_var.get()), subtitle_height=float(self.subtitle_height_var.get()), width=float(self.width_var.get()), height=float(self.height_var.get()), margin=float(self.margin_var.get()), border=self.border_var.get(), depth=float(self.depth_var.get()), safe_z=float(self.safe_z_var.get()), cut_feed=float(self.cut_feed_var.get()), plunge_feed=float(self.plunge_feed_var.get()), spindle_rpm=int(self.spindle_rpm_var.get()) if self.start_spindle_var.get() else None)

    def _update_subtitle_state(self) -> None:
        self.subtitle_entry.configure(state="normal" if self.subtitle_enabled_var.get() else "disabled")

    def _schedule_preview(self) -> None:
        if self._preview_after: self.after_cancel(self._preview_after)
        self._preview_after = self.after(80, self._refresh_preview)

    def _refresh_preview(self) -> None:
        self._preview_after = None
        try:
            self._preview = self._make()
            self.summary_var.set(f"Preview: {self._preview.width:g} × {self._preview.height:g} mm; {self._preview.stroke_count} cutting strokes.")
        except (ValueError, tk.TclError) as exc:
            self._preview = None; self.summary_var.set(f"Preview needs a valid setting: {exc}")
        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("all")
        width, height = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        if not self._preview:
            self.canvas.create_text(width / 2, height / 2, text="Enter valid plaque settings to preview", fill="#666666"); return
        plaque, pad = self._preview, 18
        scale = min((width - 2 * pad) / plaque.width, (height - 2 * pad) / plaque.height)
        ox, oy = (width - plaque.width * scale) / 2, (height + plaque.height * scale) / 2
        for stroke in plaque.strokes:
            points = [coordinate for x, y in stroke for coordinate in (ox + x * scale, oy - y * scale)]
            if len(points) >= 4: self.canvas.create_line(*points, fill="#146eb4", width=2, capstyle="round", joinstyle="round")
        self.canvas.create_rectangle(ox, oy - plaque.height * scale, ox + plaque.width * scale, oy, outline="#b8d6ec")

    def _generate(self) -> PlaqueEngraving | None:
        try: return self._make()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Plaque not generated", str(exc), parent=self); return None

    def generate_and_load(self) -> None:
        engraving = self._generate()
        if not engraving: return
        self.app.job_panel.set_program(parse_gcode(engraving.gcode, Path("generated-plaque.gcode")))
        self.app._append_system_log(f"Generated plaque loaded: {engraving.width:g} x {engraving.height:g} mm")
        self.close()

    def save(self) -> None:
        engraving = self._generate()
        if not engraving: return
        selected = filedialog.asksaveasfilename(parent=self, title="Save plaque G-code", defaultextension=".gcode", initialfile="plaque.gcode", filetypes=(("G-code", "*.gcode"), ("All files", "*.*")))
        if not selected: return
        try: Path(selected).write_text(engraving.gcode, encoding="ascii")
        except OSError as exc: messagebox.showerror("G-code not saved", str(exc), parent=self); return
        self.app.job_panel.set_program(parse_gcode(engraving.gcode, Path(selected)))
        self.app._append_system_log(f"Generated plaque saved and loaded: {selected}")

    def close(self) -> None:
        self.app.plaque_engraver_window = None
        self.destroy()
