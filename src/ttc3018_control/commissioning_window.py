from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .commissioning import CommissioningProfile, CommissioningStore, InputTestTracker
from .grbl import GrblStatus, make_setting, parse_setting

if TYPE_CHECKING:
    from .app import ControllerApp
    from .serial_connection import SerialEvent


class CommissioningWindow(tk.Toplevel):
    """Guided, gated commissioning UI. Constructing this window sends no commands."""

    SETTING_ROWS = (
        (5, "Limit input inversion", "0 or 1", "Must make X/Y/Z inactive at rest"),
        (6, "Probe input inversion", "0 or 1", "Must make P inactive when open"),
        (20, "Soft limits", "0", "Keep off until homing is verified"),
        (21, "Hard limits", "0", "Keep off for the first homing test"),
        (22, "Homing cycle", "1", "Enable homing"),
        (23, "Homing direction mask", "0–7", "Machine-specific; verify before motion"),
        (24, "Homing locate speed", "25", "Slow precision pass, mm/min"),
        (25, "Homing seek speed", "200", "Conservative first seek, mm/min"),
        (26, "Switch debounce", "250", "Milliseconds"),
        (27, "Homing pull-off", "2", "Millimeters away from switch"),
        (130, "X maximum travel", "measured", "Millimeters"),
        (131, "Y maximum travel", "measured", "Millimeters"),
        (132, "Z maximum travel", "measured", "Millimeters"),
    )

    def __init__(self, app: ControllerApp, store: CommissioningStore) -> None:
        super().__init__(app)
        self.app = app
        self.store = store
        try:
            self.profile = store.load()
        except (OSError, ValueError, TypeError):
            self.profile = CommissioningProfile()
        self.tracker = InputTestTracker()
        self.setting_vars: dict[int, tk.StringVar] = {}
        self.current_settings: dict[int, float] = {}
        self.test_status_vars = {pin: tk.StringVar(value="Not tested") for pin in "XYZP"}
        for pin, attribute in (("X", "x_limit_tested"), ("Y", "y_limit_tested"), ("Z", "z_limit_tested"), ("P", "probe_tested")):
            if getattr(self.profile, attribute):
                self.test_status_vars[pin].set("Passed")
        self.direction_vars = {
            axis: tk.BooleanVar(value=getattr(self.profile, f"{axis.lower()}_positive_confirmed"))
            for axis in "XYZ"
        }
        self.live_pins_var = tk.StringVar(value="No status report yet")
        self.input_instruction_var = tk.StringVar(value="Start with every switch released and the probe circuit open.")
        self.summary_var = tk.StringVar()
        self.connection_var = tk.StringVar()
        self.geometry_vars = {
            "plate_thickness": tk.StringVar(value=self._number(self.profile.plate_thickness)),
            "x_edge_offset": tk.StringVar(value=self._number(self.profile.x_edge_offset)),
            "y_edge_offset": tk.StringVar(value=self._number(self.profile.y_edge_offset)),
            "hole_diameter": tk.StringVar(value=self._number(self.profile.hole_diameter)),
        }
        self.homing_attempted = False

        self.title("Machine Commissioning")
        self.geometry("920x720")
        self.minsize(820, 620)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.on_connection_changed()
        if app.status is not None:
            self.on_status(app.status)
        self._refresh()

    @staticmethod
    def _number(value: float) -> str:
        return "" if value == 0 else f"{value:g}"

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, padding=(14, 12, 14, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Guided machine commissioning", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.connection_var).grid(row=0, column=1, sticky="e")
        ttk.Label(
            header,
            text="Opening this workspace never moves the machine. Every motion command remains separately gated and confirmed.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=14, pady=8)
        self._build_inputs(notebook)
        self._build_homing(notebook)
        self._build_probe(notebook)
        self._build_summary(notebook)

        footer = ttk.Frame(self, padding=(14, 4, 14, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, text="Physical power removal remains the emergency stop.", foreground="#9b3b00").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Close", command=self.close).grid(row=0, column=1)

    def _build_inputs(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=14)
        notebook.add(page, text="1  Inputs")
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            text="Test electrical signals without moving an axis. Trigger only the named switch by hand, then release it.",
            wraplength=800,
        ).grid(row=0, column=0, sticky="w")
        live = ttk.LabelFrame(page, text="Live controller inputs", padding=12)
        live.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        ttk.Label(live, textvariable=self.live_pins_var, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(live, textvariable=self.input_instruction_var, wraplength=760).grid(row=1, column=0, sticky="w", pady=(6, 0))

        tests = ttk.LabelFrame(page, text="Press-and-release tests", padding=12)
        tests.grid(row=2, column=0, sticky="ew")
        tests.columnconfigure(1, weight=1)
        labels = {"X": "X home switch", "Y": "Y home switch", "Z": "Z home switch", "P": "Touch probe circuit"}
        for row, pin in enumerate("XYZP"):
            ttk.Label(tests, text=labels[pin], width=22).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Label(tests, textvariable=self.test_status_vars[pin]).grid(row=row, column=1, sticky="w")
            ttk.Button(tests, text="Start test", command=lambda p=pin: self.start_input_test(p)).grid(row=row, column=2, padx=(10, 0))
        ttk.Label(
            page,
            text="If inputs appear active while released, stop here. Read the current settings, correct $5 for limit polarity or $6 for probe polarity, then retest.",
            foreground="#9b3b00",
            wraplength=800,
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

    def _build_homing(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=14)
        notebook.add(page, text="2  Homing")
        page.columnconfigure(0, weight=1)
        directions = ttk.LabelFrame(page, text="Confirm physical positive directions", padding=10)
        directions.grid(row=0, column=0, sticky="ew")
        for column, axis in enumerate("XYZ"):
            text = f"{axis}+ direction confirmed" + (" (tool rises)" if axis == "Z" else "")
            ttk.Checkbutton(directions, text=text, variable=self.direction_vars[axis], command=self._directions_changed).grid(
                row=0, column=column, sticky="w", padx=(0, 18)
            )

        settings = ttk.LabelFrame(page, text="GRBL homing settings", padding=10)
        settings.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        page.rowconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        for column, heading in enumerate(("Setting", "Meaning", "Value", "Commissioning note")):
            ttk.Label(settings, text=heading, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, sticky="w", padx=(0, 8))
        default_values = {20: "0", 21: "0", 22: "1", 24: "25", 25: "200", 26: "250", 27: "2"}
        travel = {130: self.app.travel_vars["X"].get(), 131: self.app.travel_vars["Y"].get(), 132: self.app.travel_vars["Z"].get()}
        for row, (number, meaning, hint, note) in enumerate(self.SETTING_ROWS, start=1):
            variable = tk.StringVar(value=travel.get(number, default_values.get(number, "")))
            self.setting_vars[number] = variable
            ttk.Label(settings, text=f"${number}", font=("Consolas", 10)).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(settings, text=meaning).grid(row=row, column=1, sticky="w", padx=(0, 8))
            ttk.Entry(settings, textvariable=variable, width=10).grid(row=row, column=2, sticky="w")
            ttk.Label(settings, text=f"{note} ({hint})", foreground="#555555").grid(row=row, column=3, sticky="w", padx=(8, 0))
        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.read_settings_button = ttk.Button(actions, text="Read current settings", command=self.read_settings)
        self.read_settings_button.grid(row=0, column=0)
        self.polarity_button = ttk.Button(actions, text="Apply input polarity…", command=self.apply_input_polarity)
        self.polarity_button.grid(row=0, column=1, padx=8)
        self.apply_settings_button = ttk.Button(actions, text="Review and apply settings…", command=self.apply_settings)
        self.apply_settings_button.grid(row=0, column=2)
        self.home_button = ttk.Button(actions, text="Run first homing test…", command=self.run_homing)
        self.home_button.grid(row=0, column=3, padx=8)
        self.verify_home_button = ttk.Button(actions, text="Mark homing successful…", command=self.mark_homing_verified)
        self.verify_home_button.grid(row=0, column=4)
        self.enable_limits_button = ttk.Button(actions, text="Enable protections…", command=self.enable_limits)
        self.enable_limits_button.grid(row=0, column=5, padx=(8, 0))
        ttk.Label(
            page,
            text="$23 mask: add 1 to reverse X, 2 to reverse Y, and 4 to reverse Z. Choose it from actual switch locations; never guess.",
            foreground="#555555",
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def _build_probe(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=14)
        notebook.add(page, text="3  Probe")
        page.columnconfigure(1, weight=1)
        ttk.Label(
            page,
            text="Use the XYZ plate temporarily on the workpiece. Enter dimensions measured from the plate—not values printed in an advertisement.",
            wraplength=800,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        rows = (
            ("plate_thickness", "Top surface thickness", "Required for Z work zero"),
            ("x_edge_offset", "X contact-to-edge offset", "Used by a future X edge routine"),
            ("y_edge_offset", "Y contact-to-edge offset", "Used by a future Y edge routine"),
            ("hole_diameter", "Center hole diameter", "Used by a future bore-center routine"),
        )
        for row, (name, label, note) in enumerate(rows, start=1):
            ttk.Label(page, text=label).grid(row=row, column=0, sticky="w", pady=6)
            ttk.Entry(page, textvariable=self.geometry_vars[name], width=12).grid(row=row, column=1, sticky="w", padx=10)
            ttk.Label(page, text=f"mm — {note}", foreground="#555555").grid(row=row, column=2, sticky="w")
        ttk.Button(page, text="Save measured plate geometry", command=self.save_probe_geometry).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Separator(page).grid(row=6, column=0, columnspan=3, sticky="ew", pady=18)
        ttk.Label(
            page,
            text="Probe motion remains unavailable until the electrical probe test, homing verification, and a nonzero measured plate thickness are complete. This commissioning version intentionally validates the circuit without moving the tool.",
            wraplength=800,
        ).grid(row=7, column=0, columnspan=3, sticky="w")
        self.probe_ready_label = ttk.Label(page)
        self.probe_ready_label.grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _build_summary(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=18)
        notebook.add(page, text="4  Checklist")
        ttk.Label(page, text="Commissioning status", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(page, textvariable=self.summary_var, justify="left", font=("Segoe UI", 11)).grid(row=1, column=0, sticky="nw", pady=(14, 0))
        ttk.Label(
            page,
            text="After successful homing, hard and soft limits should be enabled as a separate protection step. Test hard limits at low speed before relying on them.",
            wraplength=760,
            foreground="#555555",
        ).grid(row=2, column=0, sticky="w", pady=(20, 0))

    def start_input_test(self, pin: str) -> None:
        if self.app.status is None:
            messagebox.showwarning("No live status", "Connect to the controller and wait for a status report.", parent=self)
            return
        result = self.tracker.start(pin, self.app.status.pins)
        self.input_instruction_var.set(result.message)
        self.test_status_vars[pin].set("Testing" if result.state == "awaiting_press" else result.message)

    def on_status(self, status: GrblStatus) -> None:
        pins = status.pins or ""
        self.live_pins_var.set(f"Active: {pins}" if pins else "Active: none (correct at rest)")
        if self.tracker.target is not None and self.tracker.state in {"awaiting_press", "awaiting_release"}:
            result = self.tracker.update(pins)
            self.input_instruction_var.set(result.message)
            self.test_status_vars[self.tracker.target].set(result.message)
            if result.passed:
                attribute = "probe_tested" if self.tracker.target == "P" else f"{self.tracker.target.lower()}_limit_tested"
                setattr(self.profile, attribute, True)
                self._save()
        self._refresh()

    def on_event(self, event: SerialEvent) -> None:
        if event.kind != "rx":
            return
        parsed = parse_setting(event.text)
        if parsed is not None and parsed[0] in self.setting_vars:
            number, value = parsed
            self.current_settings[number] = value
            self.setting_vars[number].set(f"{value:g}")

    def on_connection_changed(self) -> None:
        connected = self.app.connection.connected
        self.connection_var.set("Controller connected" if connected else "Controller disconnected")
        self._refresh()

    def _directions_changed(self) -> None:
        for axis, variable in self.direction_vars.items():
            setattr(self.profile, f"{axis.lower()}_positive_confirmed", variable.get())
        self._save()

    def read_settings(self) -> None:
        if not self._require_connected_idle("read settings"):
            return
        try:
            self.app.connection.send_line(b"$$\n")
        except RuntimeError as exc:
            messagebox.showerror("Settings not requested", str(exc), parent=self)

    def _setting_values(self) -> dict[int, float]:
        values: dict[int, float] = {}
        for number, variable in self.setting_vars.items():
            text = variable.get().strip()
            if not text:
                raise ValueError(f"${number} is blank. Read the controller settings and review every value.")
            values[number] = float(text)
        for number in (5, 6, 20, 21, 22):
            if values[number] not in {0, 1}:
                raise ValueError(f"${number} must be 0 or 1")
        if values[23] not in range(8):
            raise ValueError("$23 must be a whole-number direction mask from 0 through 7")
        if values[20] != 0 or values[21] != 0 or values[22] != 1:
            raise ValueError("For the first homing test, require $20=0, $21=0, and $22=1")
        if min(values[24], values[25], values[26], values[27], values[130], values[131], values[132]) <= 0:
            raise ValueError("Speeds, debounce, pull-off, and all travel values must be greater than zero")
        return values

    def apply_input_polarity(self) -> None:
        if not self._require_connected_idle("apply input polarity"):
            return
        try:
            values = {number: float(self.setting_vars[number].get().strip()) for number in (5, 6)}
            if any(value not in {0, 1} for value in values.values()):
                raise ValueError("$5 and $6 must each be 0 or 1")
        except ValueError as exc:
            messagebox.showerror("Polarity incomplete", f"Read the current settings, then enter 0 or 1 for both $5 and $6.\n\n{exc}", parent=self)
            return
        if not messagebox.askyesno(
            "Apply input polarity?",
            f"Write $5={values[5]:g} and $6={values[6]:g}? This cannot move the machine. All switch and probe tests must then be repeated.",
            icon="warning",
            parent=self,
        ):
            return
        try:
            for number, value in values.items():
                self.app.connection.send_line(make_setting(number, value))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Polarity not applied", str(exc), parent=self)
            return
        self.current_settings.update(values)
        self._invalidate_input_tests()
        messagebox.showinfo("Polarity requested", "Release every switch and open the probe circuit. The live input display should become none; then repeat all four tests.", parent=self)

    def _invalidate_input_tests(self) -> None:
        for attribute in ("x_limit_tested", "y_limit_tested", "z_limit_tested", "probe_tested"):
            setattr(self.profile, attribute, False)
        for variable in self.test_status_vars.values():
            variable.set("Not tested")
        self.tracker = InputTestTracker()
        self._save()

    def apply_settings(self) -> None:
        if not self._require_connected_idle("apply settings"):
            return
        try:
            values = self._setting_values()
        except ValueError as exc:
            messagebox.showerror("Settings incomplete", str(exc), parent=self)
            return
        polarity_changed = any(
            number in self.current_settings and self.current_settings[number] != values[number]
            for number in (5, 6)
        )
        details = "\n".join(f"${number} = {value:g}" for number, value in values.items())
        if not messagebox.askyesno(
            "Apply commissioning settings?",
            "These values will be written to GRBL. The machine will not move. Verify the inversion and homing-direction values against the live wiring first.\n\n" + details,
            icon="warning",
            parent=self,
        ):
            return
        try:
            for number, value in values.items():
                self.app.connection.send_line(make_setting(number, value))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Settings not applied", str(exc), parent=self)
            return
        self.profile.homing_settings_reviewed = True
        self.profile.homing_verified = False
        self.current_settings.update(values)
        if polarity_changed:
            self._invalidate_input_tests()
        self._save()
        messagebox.showinfo("Settings sent", "GRBL accepted the settings queue. Retest all inputs before the first homing cycle if polarity changed.", parent=self)

    def run_homing(self) -> None:
        if not self.app.connection.connected or self.app.status is None or self.app.status.state not in {"Idle", "Alarm"}:
            messagebox.showwarning("Controller not ready", "Connect and wait for GRBL to report Idle or Alarm before homing.", parent=self)
            return
        if not self.profile.ready_for_homing_test:
            messagebox.showwarning("Homing locked", "Complete all three switch tests, direction confirmations, and the settings review first.", parent=self)
            return
        if self.app.status and self.app.status.pins:
            messagebox.showwarning("Homing locked", f"Inputs are active at rest: {self.app.status.pins}. Release or correct them first.", parent=self)
            return
        if not messagebox.askyesno(
            "Run the first homing cycle?",
            "This WILL MOVE all axes toward their configured home directions. Keep one hand at physical power, remove the probe plate, raise the tool clear of fixtures, and be ready to cut power if any axis travels the wrong way.\n\nContinue with $H?",
            icon="warning",
            parent=self,
        ):
            return
        try:
            self.app.invalidate_reference("GRBL homing cycle started")
            self.app.connection.send_line(b"$H\n")
            self.homing_attempted = True
        except RuntimeError as exc:
            messagebox.showerror("Homing not started", str(exc), parent=self)
        self._refresh()

    def mark_homing_verified(self) -> None:
        if not self.homing_attempted or self.app.status is None or self.app.status.state != "Idle":
            messagebox.showwarning("Cannot verify", "Run a homing cycle and wait for GRBL to return to Idle first.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirm successful homing",
            "Did every axis reach its intended switch, stop, pull away, and return to Idle without a crash or alarm?",
            parent=self,
        ):
            return
        self.profile.homing_verified = True
        self._save()

    def enable_limits(self) -> None:
        if not self._require_connected_idle("enable protections"):
            return
        if not self.profile.homing_verified:
            messagebox.showwarning("Protections locked", "Physically verify a successful homing cycle first.", parent=self)
            return
        if not messagebox.askyesno(
            "Enable hard and soft limits?",
            "This writes $21=1 and $20=1. It assumes the switch polarity and maximum travel values were tested, and that the current machine position came from a successful homing cycle. An active switch can immediately cause an alarm.\n\nEnable both protections?",
            icon="warning",
            parent=self,
        ):
            return
        try:
            self.app.connection.send_line(make_setting(21, 1))
            self.app.connection.send_line(make_setting(20, 1))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Protections not enabled", str(exc), parent=self)
            return
        self.setting_vars[21].set("1")
        self.setting_vars[20].set("1")
        messagebox.showinfo("Protections requested", "Hard and soft limits were sent to GRBL. Verify the communication log for ok responses.", parent=self)

    def save_probe_geometry(self) -> None:
        try:
            for name, variable in self.geometry_vars.items():
                setattr(self.profile, name, float(variable.get().strip() or 0))
            self.profile.validate()
            self._save()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Geometry not saved", str(exc), parent=self)
            return
        messagebox.showinfo("Probe geometry saved", "Measured plate values were saved. No machine command was sent.", parent=self)

    def _require_connected_idle(self, action: str) -> bool:
        if not self.app.connection.connected or self.app.status is None or self.app.status.state != "Idle":
            messagebox.showwarning("Controller not ready", f"Connect and wait for GRBL to report Idle before attempting to {action}.", parent=self)
            return False
        return True

    def _save(self) -> None:
        try:
            self.store.save(self.profile)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Commissioning progress not saved", str(exc), parent=self)
        self._refresh()

    def _refresh(self) -> None:
        connected = self.app.connection.connected
        idle = connected and self.app.status is not None and self.app.status.state == "Idle"
        home_ready_state = connected and self.app.status is not None and self.app.status.state in {"Idle", "Alarm"}
        if hasattr(self, "read_settings_button"):
            self.read_settings_button.configure(state="normal" if idle else "disabled")
            self.polarity_button.configure(state="normal" if idle else "disabled")
            self.apply_settings_button.configure(state="normal" if idle else "disabled")
            self.home_button.configure(state="normal" if home_ready_state and self.profile.ready_for_homing_test else "disabled")
            self.verify_home_button.configure(state="normal" if idle and self.homing_attempted else "disabled")
            self.enable_limits_button.configure(state="normal" if idle and self.profile.homing_verified else "disabled")
        done = lambda value: "✓" if value else "○"
        self.summary_var.set(
            f"{done(self.profile.x_limit_tested)} X switch tested\n"
            f"{done(self.profile.y_limit_tested)} Y switch tested\n"
            f"{done(self.profile.z_limit_tested)} Z switch tested\n"
            f"{done(self.profile.probe_tested)} Probe circuit tested\n\n"
            f"{done(self.profile.directions_confirmed)} Positive motion directions confirmed\n"
            f"{done(self.profile.homing_settings_reviewed)} Homing settings reviewed and applied\n"
            f"{done(self.profile.homing_verified)} Homing cycle physically verified"
        )
        if hasattr(self, "probe_ready_label"):
            if self.profile.ready_for_probe_motion:
                self.probe_ready_label.configure(text="Probe prerequisites complete — ready for a separately designed probing routine.", foreground="#087a2f")
            else:
                self.probe_ready_label.configure(text="Probe motion locked — commissioning prerequisites are incomplete.", foreground="#9b3b00")

    def close(self) -> None:
        self.app.commissioning_window = None
        self.destroy()
