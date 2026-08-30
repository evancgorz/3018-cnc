from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import ttkbootstrap as tb

from .connection_settings import (
    ConnectionSettings,
    ConnectionSettingsStore,
    extract_controller_ip,
)
from .commissioning import CommissioningStore
from .commissioning_window import CommissioningWindow
from .grbl import (
    GrblStatus,
    Position,
    REALTIME_HOLD,
    REALTIME_JOG_CANCEL,
    REALTIME_RESUME,
    REALTIME_SOFT_RESET,
    REALTIME_STATUS,
    make_jog,
    make_work_zero,
    parse_status,
)
from .gcode import GCodeProgram
from .job import JobStreamer
from .job_panel import JobPanel
from .machine_state import (
    MachineProfile,
    ProfileStore,
    VirtualEnvelope,
    check_job_bounds,
    plan_safe_position_jogs,
    work_zero_virtual_target,
)
from .serial_connection import GrblConnection, SerialEvent, available_ports
from .setup_wizard import SetupWizard
from .tcp_connection import TcpGrblConnection
from .text_engraver_window import TextEngraverWindow
from .plaque_engraver_window import PlaqueEngraverWindow
from .wifi_setup import make_station_commands
from .wifi_discovery import discover_grbl_hosts


class ControllerApp(tk.Tk):
    POLL_MS = 500

    def __init__(self) -> None:
        super().__init__()
        self.title("TTC 3018 Control — Manual Setup & Engraving")
        self.geometry("1480x880")
        self.minsize(1180, 760)

        self.connection = GrblConnection()
        self.status: GrblStatus | None = None
        self.work_offset: Position | None = None
        self.envelope = VirtualEnvelope()
        self.unreferenced_jog_acknowledged = False
        self._log_redactions: set[str] = set()
        self._wifi_setup_commands: list[tuple[bytes, str]] = []
        self._wifi_setup_index = 0
        self._wifi_setup_waiting = False
        self._wifi_discovery_attempts = 0
        self._wifi_discovery_active = False
        self._wifi_connecting = False
        self._wifi_connect_results: queue.Queue[tuple[TcpGrblConnection | None, str, int]] = queue.Queue()
        self.log_file = self._new_log_file()
        self.profile_store = ProfileStore(Path.cwd() / "config" / "machine-profile.json")
        self.connection_settings_store = ConnectionSettingsStore(Path.cwd() / "config" / "connection.json")
        self.commissioning_store = CommissioningStore(Path.cwd() / "config" / "commissioning.json")
        self.commissioning_window: CommissioningWindow | None = None
        self.setup_wizard: SetupWizard | None = None
        self.text_engraver_window: TextEngraverWindow | None = None
        self.plaque_engraver_window: PlaqueEngraverWindow | None = None
        self.connection_window: tk.Toplevel | None = None
        self.work_zero_confirmed = False
        self._awaiting_work_zero_report = False
        try:
            self.profile = self.profile_store.load()
        except (OSError, ValueError, TypeError):
            self.profile = MachineProfile()
        try:
            self.connection_settings = self.connection_settings_store.load()
        except (OSError, ValueError, TypeError):
            self.connection_settings = ConnectionSettings()

        self.port_var = tk.StringVar(value="COM3")
        self.transport_var = tk.StringVar(value=self.connection_settings.preferred_transport)
        self.wifi_host_var = tk.StringVar(value=self.connection_settings.wifi_host)
        self.wifi_port_var = tk.IntVar(value=self.connection_settings.wifi_port)
        self.connection_var = tk.StringVar(value="Disconnected")
        self.state_var = tk.StringVar(value="Unknown")
        self.machine_position_vars = {axis: tk.StringVar(value="—") for axis in "XYZ"}
        self.work_position_vars = {axis: tk.StringVar(value="—") for axis in "XYZ"}
        self.reference_position_vars = {axis: tk.StringVar(value="—") for axis in "XYZ"}
        self.machine_position_summary_var = tk.StringVar(value="M  X—  Y—  Z—")
        self.work_position_summary_var = tk.StringVar(value="W  X—  Y—  Z—")
        self.reference_position_summary_var = tk.StringVar(value="V  X—  Y—  Z—")
        self.feed_actual_var = tk.StringVar(value="0")
        self.spindle_var = tk.StringVar(value="0")
        self.pins_var = tk.StringVar(value="—")
        self.reference_var = tk.StringVar(value="POSITION UNKNOWN — virtual limits inactive")
        self.work_zero_state_var = tk.StringVar(value="XYZ work zero not confirmed for this session")
        self.action_status_var = tk.StringVar(value="Ready")
        self._action_status_revision = 0
        self.step_var = tk.DoubleVar(value=1.0)
        self.feed_var = tk.DoubleVar(value=500.0)
        self.profile_name_var = tk.StringVar(value=self.profile.name)
        self.travel_vars = {
            "X": tk.StringVar(value=self._profile_value(self.profile.travel_x)),
            "Y": tk.StringVar(value=self._profile_value(self.profile.travel_y)),
            "Z": tk.StringVar(value=self._profile_value(self.profile.travel_z)),
        }
        self.safe_z_var = tk.StringVar(value=self._profile_value(self.profile.safe_z))
        self.position_target_vars = {axis: tk.StringVar(value="0") for axis in "XYZ"}
        self.motion_controls: list[ttk.Button] = []
        self._pending_manual_acks = 0
        self._position_move_queue: list[tuple[str, float, float]] = []
        self._position_move_active = False
        self._position_move_completion = ""
        self._return_after_job_pending = False
        self._preserve_references_on_next_reset = False
        self.job = JobStreamer(lambda command: self.connection.send_line(command))
        self.job_panel: JobPanel

        self._build_ui()
        self._show_reference_state()
        self.refresh_ports()
        self._update_transport_fields()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(50, self._process_events)
        self.after(self.POLL_MS, self._poll_status)

    @staticmethod
    def _profile_value(value: float) -> str:
        return "" if value == 0 else f"{value:g}"

    def _new_log_file(self) -> Path:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(exist_ok=True)
        return log_dir / f"session-{datetime.now():%Y%m%d-%H%M%S}.log"

    def _build_ui(self) -> None:
        style = tb.Style(theme="darkly")
        self.configure(background="#22252a")
        style.configure("Trusted.TLabel", foreground="#4ade80", font=("Segoe UI", 10, "bold"))
        style.configure("Unknown.TLabel", foreground="#fbbf24", font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Coordinate.TLabel", font=("Cascadia Mono", 14, "bold"), foreground="#f8fafc")
        style.configure("Section.TLabelframe", padding=12, borderwidth=0, relief="flat")
        style.configure("Section.TLabelframe.Label", font=("Segoe UI Semibold", 10))
        self._build_soft_button_styles(style)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self, padding=(16, 14, 16, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="TTC 3018 CONTROL", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(toolbar, textvariable=self.connection_var).grid(row=0, column=1, sticky="w")
        toolbar.columnconfigure(1, weight=1)
        self.connect_button = ttk.Button(toolbar, text="Connect", command=self.open_connection_window, style="SoftAccent.TButton")
        self.connect_button.grid(row=0, column=2, padx=4)
        self.wifi_top_button = ttk.Button(toolbar, text="Wi-Fi Setup…", command=self.configure_house_wifi, state="disabled")
        self.wifi_top_button.grid(row=0, column=3, padx=4)
        ttk.Button(toolbar, text="Commissioning…", command=self.open_commissioning).grid(row=0, column=4, padx=4)
        ttk.Button(toolbar, text="Guided Setup Wizard…", command=self.open_setup_wizard).grid(row=0, column=5, padx=(4, 0))

        dashboard = ttk.Frame(self, padding=(16, 4))
        dashboard.grid(row=1, column=0, sticky="ew")
        dashboard.columnconfigure(0, weight=1)
        machine_strip = ttk.LabelFrame(dashboard, text="Live machine state", style="Section.TLabelframe")
        machine_strip.grid(row=0, column=0, sticky="ew")
        for column in range(7):
            machine_strip.columnconfigure(column, weight=1 if column >= 4 else 0)
        for column, (label, variable) in enumerate(
            (("State", self.state_var), ("Feed", self.feed_actual_var), ("Spindle", self.spindle_var), ("Pins", self.pins_var))
        ):
            ttk.Label(machine_strip, text=f"{label}:", style="Header.TLabel").grid(row=0, column=column * 2, sticky="w", padx=(0 if column == 0 else 12, 4))
            ttk.Label(machine_strip, textvariable=variable).grid(row=0, column=column * 2 + 1, sticky="w")
        ttk.Separator(machine_strip, orient="vertical").grid(row=0, column=8, sticky="ns", padx=14)
        ttk.Label(machine_strip, textvariable=self.machine_position_summary_var, style="Coordinate.TLabel").grid(row=0, column=9, sticky="w", padx=(0, 14))
        ttk.Label(machine_strip, textvariable=self.work_position_summary_var, style="Coordinate.TLabel").grid(row=0, column=10, sticky="w", padx=(0, 14))
        ttk.Label(machine_strip, textvariable=self.reference_position_summary_var, style="Coordinate.TLabel").grid(row=0, column=11, sticky="w")

        body = ttk.Panedwindow(self, orient="vertical")
        body.grid(row=2, column=0, sticky="nsew", padx=16, pady=(6, 10))
        controls_shell = ttk.Frame(body, padding=(0, 0, 8, 0))
        body.add(controls_shell, weight=2)
        controls_shell.columnconfigure(0, weight=1)
        controls = ttk.Frame(controls_shell)
        controls.grid(row=0, column=0, sticky="ew")
        for column in range(3):
            controls.columnconfigure(column, weight=1)

        motion = ttk.LabelFrame(controls, text="1. Position the machine", style="Section.TLabelframe")
        motion.grid(row=0, column=0, columnspan=3, sticky="ew")
        motion.columnconfigure(0, weight=1)
        motion.columnconfigure(1, weight=1)
        motion.columnconfigure(2, weight=1)
        ttk.Label(motion, text="Step (mm)").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            motion,
            textvariable=self.step_var,
            values=(0.1, 1.0, 5.0, 10.0, 20.0),
            state="readonly",
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(motion, text="Feed (mm/min)").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(motion, from_=1, to=1500, textvariable=self.feed_var, width=11).grid(row=0, column=2, sticky="e", padx=8)
        jogs = ttk.Frame(motion)
        jogs.grid(row=1, column=0, pady=8, sticky="w")
        for text, axis, sign, row, column in [
            ("Y +", "Y", 1, 0, 1),
            ("X −", "X", -1, 1, 0),
            ("X +", "X", 1, 1, 2),
            ("Y −", "Y", -1, 2, 1),
            ("Z + (up)", "Z", 1, 0, 3),
            ("Z − (down)", "Z", -1, 1, 3),
        ]:
            button = ttk.Button(jogs, text=text, command=lambda a=axis, s=sign: self.jog(a, s), width=13, style="Soft.TButton")
            button.grid(row=row, column=column, padx=4, pady=4)
            self.motion_controls.append(button)
        actions = ttk.Frame(motion)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 0))
        for column, (text, command) in enumerate(
            [
                ("Feed hold", lambda: self.realtime(REALTIME_HOLD)),
                ("Resume", lambda: self.realtime(REALTIME_RESUME)),
                ("Cancel jog", lambda: self.realtime(REALTIME_JOG_CANCEL)),
            ]
        ):
            button = ttk.Button(actions, text=text, command=command, style="Soft.TButton")
            button.grid(row=0, column=column, padx=3, sticky="ew")
            actions.columnconfigure(column, weight=1)
            self.motion_controls.append(button)

        target = ttk.LabelFrame(motion, text="Move to virtual coordinates", padding=10)
        target.grid(row=1, column=1, rowspan=2, columnspan=2, sticky="nsew", padx=(16, 0), pady=4)
        for column, axis in enumerate("XYZ"):
            ttk.Label(target, text=axis).grid(row=0, column=column * 2, padx=(4, 2), pady=4)
            ttk.Entry(target, textvariable=self.position_target_vars[axis], width=9).grid(row=0, column=column * 2 + 1, padx=(0, 8), pady=4)
        jog_to_position = ttk.Button(target, text="Move safely to position", command=self.jog_to_position, style="SoftAccent.TButton")
        jog_to_position.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        self.motion_controls.append(jog_to_position)

        profile = ttk.LabelFrame(controls, text="Machine profile", style="Section.TLabelframe")
        profile.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(8, 0))
        profile.columnconfigure(1, weight=1)
        ttk.Label(profile, text="Machine name").grid(row=0, column=0, sticky="w")
        ttk.Entry(profile, textvariable=self.profile_name_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        for row, axis in enumerate("XYZ", start=1):
            ttk.Label(profile, text=f"{axis} travel (mm)").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(profile, textvariable=self.travel_vars[axis], width=10).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Label(profile, text="Safe Z (from reference)").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(profile, textvariable=self.safe_z_var, width=10).grid(row=4, column=1, sticky="ew", padx=8)
        ttk.Button(profile, text="Save profile", command=self.save_profile).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        reference = ttk.LabelFrame(controls, text="2. Set machine reference", style="Section.TLabelframe")
        reference.grid(row=1, column=1, sticky="nsew", padx=4, pady=(8, 0))
        reference.columnconfigure(1, weight=1)
        self.reference_label = ttk.Label(reference, textvariable=self.reference_var, style="Unknown.TLabel")
        self.reference_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        establish = ttk.Button(reference, text="Set machine reference here", command=self.establish_reference, style="SoftAccent.TButton")
        establish.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 4))
        invalidate = ttk.Button(reference, text="Invalidate", command=lambda: self.invalidate_reference("Manually invalidated"))
        invalidate.grid(row=1, column=2, sticky="ew", padx=4)
        safe_z = ttk.Button(reference, text="Retract to safe Z", command=self.retract_safe_z)
        safe_z.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        return_to_reference = ttk.Button(
            reference,
            text="Return to reference (via safe Z, ends at Z0)",
            command=self.return_to_reference,
        )
        return_to_reference.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.motion_controls.extend([establish, invalidate, safe_z, return_to_reference])

        work_zero = ttk.LabelFrame(controls, text="3. Set work zero (no movement)", style="Section.TLabelframe")
        work_zero.grid(row=1, column=2, sticky="nsew", padx=(4, 0), pady=(8, 0))
        for column, axes in enumerate(("X", "Y", "Z", "XYZ")):
            button = ttk.Button(work_zero, text=f"Zero {axes}", command=lambda a=axes: self.set_work_zero(a), style="SoftAccent.TButton" if axes == "XYZ" else "Soft.TButton")
            button.grid(row=0, column=column, sticky="ew", padx=3)
            work_zero.columnconfigure(column, weight=1)
            self.motion_controls.append(button)
        reset = ttk.Button(work_zero, text="Soft reset…", command=self.soft_reset, style="SoftDanger.TButton")
        reset.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        return_to_work_zero = ttk.Button(
            work_zero,
            text="Return to work zero (via safe Z)",
            command=self.return_to_work_zero,
            style="SoftAccent.TButton",
        )
        return_to_work_zero.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.motion_controls.extend([reset, return_to_work_zero])

        lower = ttk.Panedwindow(body, orient="horizontal")
        body.add(lower, weight=3)
        self.job_panel = JobPanel(lower, self)
        lower.add(self.job_panel, weight=3)

        log_frame = ttk.LabelFrame(lower, text="Session log", style="Section.TLabelframe")
        lower.add(log_frame, weight=2)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, state="disabled", wrap="none", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        ttk.Label(log_frame, text=f"Saved to {self.log_file}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            self,
            textvariable=self.action_status_var,
            anchor="w",
            relief="sunken",
            padding=(8, 4),
            style="Header.TLabel",
        ).grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 10))
        self._set_motion_controls(False)

    def _update_connection_action_buttons(self) -> None:
        self.wifi_top_button.configure(
            state="normal" if self.connection.connected and isinstance(self.connection, GrblConnection) else "disabled"
        )

    @staticmethod
    def _build_soft_button_styles(style: tb.Style) -> None:
        """Use low-contrast, flat controls that feel lighter than native ttk buttons."""
        definitions = (
            ("Soft.TButton", "#343b45", "#454f5c", "#262c34", "#e5e7eb"),
            ("SoftAccent.TButton", "#2563eb", "#3b82f6", "#1d4ed8", "#ffffff"),
            ("SoftDanger.TButton", "#b91c1c", "#dc2626", "#7f1d1d", "#ffffff"),
        )
        for name, normal, hover, disabled, foreground in definitions:
            style.configure(name, background=normal, foreground=foreground, borderwidth=0, relief="flat", padding=(14, 8))
            style.map(name, background=[("active", hover), ("disabled", disabled)], foreground=[("disabled", "#7f8793")])

    def refresh_ports(self) -> None:
        if not hasattr(self, "port_combo"):
            return
        ports = available_ports()
        labels = [f"{device} — {description}" for device, description in ports]
        self.port_combo["values"] = labels
        preferred = next((label for label in labels if label.startswith("COM3 ")), None)
        if preferred:
            self.port_var.set(preferred)
        elif labels:
            self.port_var.set(labels[0])

    def open_connection_window(self) -> None:
        if self.connection.connected:
            self.connection.disconnect()
            self._disconnected_ui()
            return
        if self.connection_window is not None and self.connection_window.winfo_exists():
            self.connection_window.lift()
            self.connection_window.focus_force()
            return
        window = tk.Toplevel(self)
        self.connection_window = window
        window.title("Connect to TTC 3018")
        window.transient(self)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self._close_connection_window)
        frame = ttk.Frame(window, padding=14)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Transport").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.transport_combo = ttk.Combobox(frame, textvariable=self.transport_var, values=("USB serial", "Wi-Fi TCP"), state="readonly", width=22)
        self.transport_combo.grid(row=0, column=1, sticky="ew")
        self.transport_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_transport_fields())
        ttk.Label(frame, text="USB serial port").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, state="readonly", width=32)
        self.port_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        self.refresh_button = ttk.Button(frame, text="Refresh ports", command=self.refresh_ports)
        self.refresh_button.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="Wi-Fi host").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.wifi_host_entry = ttk.Entry(frame, textvariable=self.wifi_host_var)
        self.wifi_host_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(frame, text="TCP port").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.wifi_port_entry = ttk.Spinbox(frame, from_=1, to=65535, textvariable=self.wifi_port_var, width=10)
        self.wifi_port_entry.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.wifi_setup_button = ttk.Button(frame, text="Wi-Fi Setup…", command=self.configure_house_wifi)
        self.wifi_setup_button.grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Label(frame, textvariable=self.connection_var, wraplength=390).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(frame); buttons.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._close_connection_window).pack(side="left")
        ttk.Button(buttons, text="Connect", command=self.toggle_connection).pack(side="right")
        self.refresh_ports()
        self._update_transport_fields()
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_width()) // 2
        y = (window.winfo_screenheight() - window.winfo_height()) // 2
        window.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _close_connection_window(self) -> None:
        if self.connection_window is not None and self.connection_window.winfo_exists():
            self.connection_window.destroy()
        self.connection_window = None

    def open_commissioning(self) -> None:
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.lift()
            self.commissioning_window.focus_force()
            return
        self.commissioning_window = CommissioningWindow(self, self.commissioning_store)

    def open_setup_wizard(self) -> None:
        if self.setup_wizard is not None and self.setup_wizard.winfo_exists():
            self.setup_wizard.lift()
            self.setup_wizard.focus_force()
            return
        self.setup_wizard = SetupWizard(self)

    def open_text_engraver(self) -> None:
        if self.job_active:
            self._set_action_status("Text engraver ignored — finish or abort the active job first")
            return
        if self.text_engraver_window is not None and self.text_engraver_window.winfo_exists():
            self.text_engraver_window.lift()
            self.text_engraver_window.focus_force()
            return
        self.text_engraver_window = TextEngraverWindow(self)

    def open_plaque_engraver(self) -> None:
        if self.job_active:
            self._set_action_status("Plaque builder ignored — finish or abort the active job first")
            return
        if self.plaque_engraver_window is not None and self.plaque_engraver_window.winfo_exists():
            self.plaque_engraver_window.lift()
            self.plaque_engraver_window.focus_force()
            return
        self.plaque_engraver_window = PlaqueEngraverWindow(self)

    def _update_transport_fields(self) -> None:
        if self.connection_window is None or not self.connection_window.winfo_exists():
            return
        if self.connection.connected:
            self.transport_combo.configure(state="disabled")
            self.port_combo.configure(state="disabled")
            self.refresh_button.configure(state="disabled")
            self.wifi_host_entry.configure(state="disabled")
            self.wifi_port_entry.configure(state="disabled")
            self.wifi_setup_button.configure(
                state="normal" if isinstance(self.connection, GrblConnection) else "disabled"
            )
            return
        self.transport_combo.configure(state="readonly")
        usb = self.transport_var.get() == "USB serial"
        self.port_combo.configure(state="readonly" if usb else "disabled")
        self.refresh_button.configure(state="normal" if usb else "disabled")
        self.wifi_host_entry.configure(state="disabled" if usb else "normal")
        self.wifi_port_entry.configure(state="disabled" if usb else "normal")
        self.wifi_setup_button.configure(state="disabled")

    def toggle_connection(self) -> None:
        if self._wifi_connecting:
            self.connection_var.set("Wi-Fi discovery is already running…")
            return
        if self.connection.connected:
            self.connection.disconnect()
            self._disconnected_ui()
            return
        try:
            if self.transport_var.get() == "USB serial":
                port = self.port_var.get().split(" ", 1)[0]
                if not port:
                    raise ValueError("Select a serial port first")
                connection = GrblConnection()
                connection.connect(port)
                endpoint = port
            else:
                tcp_port = int(self.wifi_port_var.get())
                if not 1 <= tcp_port <= 65535:
                    raise ValueError("TCP port must be between 1 and 65535")
                self._begin_wifi_connection(self.wifi_host_var.get().strip(), tcp_port)
                return
        except (OSError, ValueError, RuntimeError) as exc:
            self.connection_var.set(f"Connection failed: {exc}")
            return
        self.connection = connection
        if self.transport_var.get() == "Wi-Fi TCP":
            self._save_connection_settings(host, tcp_port, preferred_transport="Wi-Fi TCP")
        self.connect_button.configure(text="Disconnect")
        self.connection_var.set(f"Connected to {endpoint}; waiting for GRBL status")
        self._close_connection_window()
        self._update_connection_action_buttons()
        self._update_transport_fields()

    def _begin_wifi_connection(self, configured_host: str, port: int) -> None:
        self._wifi_connecting = True
        self.connect_button.configure(state="disabled")
        self.connection_var.set(
            f"Trying {configured_host}:{port}; if unavailable, the app will discover GRBL on the local network…"
        )

        def worker() -> None:
            last_error = "No GRBL controller answered on the local network"
            if configured_host:
                connection = TcpGrblConnection()
                try:
                    connection.connect(configured_host, port, timeout=1.2)
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = str(exc)
                else:
                    self._wifi_connect_results.put((connection, configured_host, port))
                    return
            for host in discover_grbl_hosts(port):
                connection = TcpGrblConnection()
                try:
                    connection.connect(host, port, timeout=1.2)
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = str(exc)
                    continue
                self._wifi_connect_results.put((connection, host, port))
                return
            self._wifi_connect_results.put((None, last_error, port))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_wifi_connection)

    def _poll_wifi_connection(self) -> None:
        try:
            connection, result, port = self._wifi_connect_results.get_nowait()
        except queue.Empty:
            if self._wifi_connecting:
                self.after(100, self._poll_wifi_connection)
            return
        self._wifi_connecting = False
        self.connect_button.configure(state="normal")
        if connection is None:
            self.connection_var.set(
                "Wi-Fi connection failed: no GRBL endpoint was found. Confirm the controller joined this LAN and retry. "
                f"Last error: {result}"
            )
            self._update_transport_fields()
            return
        self.connection = connection
        self.wifi_host_var.set(result)
        self._save_connection_settings(result, port, preferred_transport="Wi-Fi TCP")
        self.connect_button.configure(text="Disconnect")
        self.connection_var.set(f"Connected to {result}:{port} over Wi-Fi; waiting for GRBL status")
        self._close_connection_window()
        self._update_connection_action_buttons()
        self._update_transport_fields()

    def configure_house_wifi(self) -> None:
        if not self.connection.connected or not isinstance(self.connection, GrblConnection):
            self._set_action_status("Wi-Fi setup ignored — connect through USB first")
            return
        if self.status is None or not self.status.can_jog:
            self._set_action_status("Wi-Fi setup ignored — wait for GRBL Idle")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Controller Wi-Fi Setup")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        content = ttk.Frame(dialog, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        ssid_var = tk.StringVar()
        password_var = tk.StringVar()
        ttk.Label(content, text="Network name (SSID)").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ssid_entry = ttk.Entry(content, textvariable=ssid_var, width=36)
        ssid_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(content, text="Wi-Fi password").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        ttk.Entry(content, textvariable=password_var, show="●", width=36).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(
            content,
            text=(
                "The DLC32 supports 2.4 GHz Wi-Fi. Credentials are sent over USB, "
                "stored by the controller, and never saved or logged by this application."
            ),
            wraplength=480,
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(content)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def submit() -> None:
            ssid = ssid_var.get().strip()
            password = password_var.get()
            try:
                commands = make_station_commands(ssid, password, 23)
            except ValueError as exc:
                messagebox.showerror("Invalid Wi-Fi settings", str(exc), parent=dialog)
                return
            if not messagebox.askyesno(
                "Switch controller to station mode?",
                "The controller will restart and join the selected network. The virtual position reference will be invalidated. Continue?",
                icon="warning",
                parent=dialog,
            ):
                return
            dialog.destroy()
            self._log_redactions.add(password)
            self.invalidate_reference("Controller Wi-Fi reconfiguration")
            self._invalidate_work_zero("controller Wi-Fi reconfiguration")
            self.connection_var.set("Configuring controller Wi-Fi; controller will restart…")
            self._begin_wifi_setup(commands)

        ttk.Button(buttons, text="Configure", command=submit).grid(row=0, column=1)
        ssid_entry.focus_set()
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _begin_wifi_setup(self, commands: list[tuple[bytes, str]]) -> None:
        self._wifi_setup_commands = commands
        self._wifi_setup_index = 0
        self._wifi_setup_waiting = False
        self._wifi_discovery_attempts = 0
        self._wifi_discovery_active = False
        self._send_next_wifi_setup_command()

    def _send_next_wifi_setup_command(self) -> None:
        if self._wifi_setup_index >= len(self._wifi_setup_commands):
            self._start_wifi_discovery()
            return
        if not self.connection.connected:
            messagebox.showerror("Wi-Fi setup interrupted", "The USB connection closed before setup completed.")
            self._wifi_setup_commands = []
            return
        command, display_text = self._wifi_setup_commands[self._wifi_setup_index]
        try:
            self.connection.send_line(command, display_text=display_text)
        except RuntimeError as exc:
            messagebox.showerror("Wi-Fi setup interrupted", str(exc))
            self._wifi_setup_commands = []
            return
        self.connection_var.set(
            f"Configuring controller Wi-Fi — step {self._wifi_setup_index + 1} of {len(self._wifi_setup_commands)}"
        )
        if command.startswith(b"[ESP444]"):
            self._wifi_setup_index += 1
            self._wifi_setup_waiting = False
            self.after(8000, self._start_wifi_discovery)
        else:
            self._wifi_setup_waiting = True

    def _handle_wifi_setup_response(self, response: str) -> bool:
        if not self._wifi_setup_waiting:
            return False
        lowered = response.strip().lower()
        if lowered == "ok":
            self._wifi_setup_waiting = False
            self._wifi_setup_index += 1
            self.after(100, self._send_next_wifi_setup_command)
            return True
        if lowered.startswith("error:") or lowered.startswith("alarm:"):
            self._wifi_setup_waiting = False
            self._wifi_setup_commands = []
            self.connection_var.set(f"Controller rejected Wi-Fi configuration: {response.strip()}")
            messagebox.showerror("Wi-Fi setup rejected", f"The controller returned:\n\n{response.strip()}")
            return True
        return False

    def _start_wifi_discovery(self) -> None:
        if not self._wifi_discovery_active:
            self._wifi_discovery_active = True
            self._wifi_discovery_attempts = 12
        self.connection_var.set("Wi-Fi settings saved; waiting for controller DHCP address…")
        self._request_controller_identity()

    def _request_controller_identity(self) -> None:
        if not self._wifi_discovery_active:
            return
        if self._wifi_discovery_attempts <= 0:
            self._wifi_discovery_active = False
            self._log_redactions.clear()
            self.connection_var.set(
                "Wi-Fi settings were sent, but no LAN address was reported. Confirm the network is 2.4 GHz and retry."
            )
            return
        self._wifi_discovery_attempts -= 1
        if self.connection.connected and isinstance(self.connection, GrblConnection):
            try:
                self.connection.send_line(b"$I")
            except RuntimeError:
                pass
        self.after(5000, self._request_controller_identity)

    def _save_connection_settings(
        self,
        host: str,
        port: int,
        preferred_transport: str | None = None,
    ) -> None:
        settings = ConnectionSettings(
            wifi_host=host,
            wifi_port=port,
            preferred_transport=preferred_transport or self.connection_settings.preferred_transport,
        )
        try:
            self.connection_settings_store.save(settings)
        except (OSError, ValueError) as exc:
            self._append_system_log(f"Could not save connection settings: {exc}")
            return
        self.connection_settings = settings

    def _adopt_wifi_address(self, address: str) -> None:
        if self.wifi_host_var.get() == address:
            if self.connection_settings.preferred_transport != "Wi-Fi TCP":
                self._save_connection_settings(
                    address,
                    int(self.wifi_port_var.get()),
                    preferred_transport="Wi-Fi TCP",
                )
            return
        self.wifi_host_var.set(address)
        self._save_connection_settings(
            address,
            int(self.wifi_port_var.get()),
            preferred_transport="Wi-Fi TCP",
        )
        self._append_system_log(f"Controller network address detected and saved: {address}")

    def _current_machine_position(self) -> Position | None:
        return self.status.machine_position if self.status else None

    @property
    def job_active(self) -> bool:
        return self.job.state in {"running", "paused"}

    def _send_manual_line(self, command: bytes) -> None:
        if self.job_active:
            raise RuntimeError("Manual commands cannot be sent while a job is active")
        self.connection.send_line(command)
        self._pending_manual_acks += 1

    def _job_fit(self, program: GCodeProgram) -> tuple[bool, str]:
        if not self.envelope.trusted or self.envelope.reference is None:
            return False, "Establish the manual machine reference first."
        if self.work_offset is None:
            return False, "A fresh GRBL work-offset report is required. Set work zero and wait for the display to update."
        try:
            self.profile.validate()
        except ValueError as exc:
            return False, str(exc)
        return check_job_bounds(
            Position(program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z),
            Position(program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z),
            self.work_offset,
            self.envelope.reference,
            self.profile,
        )

    def start_spindle(self) -> None:
        if self.status is None or not self.status.can_jog or self.job_active:
            self._set_action_status("Spindle start ignored — GRBL must be Idle with no active job")
            return
        try:
            rpm = int(self.job_panel.rpm_var.get())
            if not 1 <= rpm <= 24000:
                raise ValueError("Spindle speed must be between 1 and 24000 RPM")
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid spindle speed", str(exc))
            return
        if not messagebox.askyesno(
            "Start spindle?",
            f"Start the spindle clockwise at S{rpm}? Keep clear of the tool and be ready to cut physical power.",
            icon="warning",
        ):
            return
        try:
            self._send_manual_line(f"M3 S{rpm}\n".encode("ascii"))
        except RuntimeError as exc:
            messagebox.showerror("Spindle not started", str(exc))

    def stop_spindle(self) -> None:
        if self.job_active:
            self.abort_job()
            return
        try:
            self._send_manual_line(b"M5\n")
        except RuntimeError as exc:
            messagebox.showerror("Spindle not stopped", str(exc))

    def start_job(self) -> None:
        program = self.job_panel.program
        if program is None:
            messagebox.showwarning("No job", "Load a G-code file first.")
            return
        if self.status is None or not self.status.can_jog:
            messagebox.showwarning("Job blocked", "GRBL must report Idle before starting.")
            return
        if self._pending_manual_acks or self._position_move_active:
            messagebox.showwarning(
                "Job blocked",
                "Wait for the preceding spindle, jog, or zeroing command to be acknowledged before starting.",
            )
            return
        if not self.work_zero_confirmed:
            messagebox.showwarning(
                "Job blocked",
                "Set and confirm XYZ work zero for this connection session before starting the job.",
            )
            return
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            messagebox.showwarning("Job blocked", "Close the commissioning workspace before starting an engraving job.")
            return
        fits, reason = self._job_fit(program)
        if not fits:
            messagebox.showerror("Job does not fit", reason)
            return
        if not messagebox.askyesno(
            "Start engraving job?",
            f"{program.path.name}\n{len(program.commands)} commands\n\n{reason}\n\n"
            "Confirm the material and tool are secure, the manual machine reference and XYZ work zero are correct, "
            "the toolpath preview is expected, and physical emergency power is within reach. The file may control "
            "the spindle with M3/M4/M5. Continue?",
            icon="warning",
        ):
            return
        try:
            self._return_after_job_pending = False
            self.job.start(program.commands)
        except (RuntimeError, ValueError, OSError) as exc:
            messagebox.showerror("Job not started", str(exc))
            return
        self._append_system_log(f"Engraving job started: {program.path.name}")
        self._refresh_job_ui()

    def pause_job(self) -> None:
        try:
            self.connection.send_realtime(REALTIME_HOLD)
            self.job.pause()
        except RuntimeError as exc:
            messagebox.showerror("Pause failed", str(exc))
            return
        self._append_system_log("Job feed hold requested")
        self._refresh_job_ui()

    def resume_job(self) -> None:
        try:
            self.connection.send_realtime(REALTIME_RESUME)
            self.job.resume()
        except RuntimeError as exc:
            messagebox.showerror("Resume failed", str(exc))
            return
        self._append_system_log("Job resume requested")
        self._refresh_job_ui()

    def abort_job(self) -> None:
        if not self.job_active:
            return
        if not messagebox.askyesno(
            "Abort engraving?",
            "This will feed-hold and reset GRBL. The job cannot resume. The established machine reference and work zero will be retained while the machine remains connected and powered.",
            icon="warning",
        ):
            return
        try:
            self.connection.send_realtime(REALTIME_HOLD)
            self.connection.send_realtime(REALTIME_SOFT_RESET)
        except RuntimeError:
            pass
        self.job.abort()
        self._return_after_job_pending = False
        self._pending_manual_acks = 0
        self._preserve_references_on_next_reset = True
        self._append_system_log("Engraving job aborted; GRBL reset requested with references retained")
        self._refresh_job_ui()

    def _refresh_job_ui(self) -> None:
        self.job_panel.update_progress()
        self._set_motion_controls(
            self.connection.connected and not self.job_active and not self._position_move_active
        )

    def jog(self, axis: str, sign: int) -> None:
        if self._position_move_active:
            self._set_action_status("Jog ignored — a position move is active")
            return
        if self.job_active:
            self._set_action_status("Jog ignored — an engraving job is active")
            return
        if self.status is None or not self.status.can_jog:
            self._set_action_status("Jog ignored — GRBL is not Idle")
            return
        position = self._current_machine_position()
        if position is None:
            self._set_action_status("Jog ignored — waiting for a machine-position report")
            return
        try:
            distance = float(self.step_var.get()) * sign
            feed = float(self.feed_var.get())
            if self.envelope.trusted:
                allowed, reason = self.envelope.check_jog(axis, distance, position, self.profile)
                if not allowed:
                    self._set_action_status(f"Jog blocked by virtual limit — {reason}")
                    return
            elif not self.unreferenced_jog_acknowledged:
                self.unreferenced_jog_acknowledged = True
                self._set_action_status("Unreferenced jogging enabled for this session — virtual limits are inactive")
            self._send_manual_line(make_jog(axis, distance, feed))
        except (ValueError, RuntimeError) as exc:
            self._set_action_status(f"Jog not sent — {exc}")

    def save_profile(self) -> None:
        try:
            profile = MachineProfile(
                name=self.profile_name_var.get().strip(),
                travel_x=float(self.travel_vars["X"].get()),
                travel_y=float(self.travel_vars["Y"].get()),
                travel_z=float(self.travel_vars["Z"].get()),
                safe_z=float(self.safe_z_var.get()),
            )
            self.profile_store.save(profile)
        except (ValueError, OSError) as exc:
            self._set_action_status(f"Profile not saved — {exc}")
            return
        self.profile = profile
        self._set_action_status("Machine profile saved; reference and work zero were retained")

    def establish_reference(self) -> None:
        position = self._current_machine_position()
        if self.status is None or not self.status.can_jog or position is None:
            self._set_action_status("Reference ignored — connect and wait for GRBL Idle with a machine position")
            return
        try:
            self.profile.validate()
        except ValueError as exc:
            self._set_action_status(f"Reference ignored — save a valid machine profile first: {exc}")
            return
        self.envelope.establish(position, self.profile)
        self._invalidate_work_zero("Set XYZ work zero after establishing the machine reference")
        self.unreferenced_jog_acknowledged = False
        self._show_reference_state()
        self._append_system_log("Virtual reference established at current GRBL machine position")
        self._set_action_status("Virtual machine reference established at the current position")

    def invalidate_reference(self, reason: str) -> None:
        was_trusted = self.envelope.trusted
        self.envelope.invalidate(reason)
        self.unreferenced_jog_acknowledged = False
        self._show_reference_state()
        if was_trusted:
            self._append_system_log(f"Virtual reference invalidated: {reason}")

    def _invalidate_work_zero(self, reason: str) -> None:
        self.work_zero_confirmed = False
        self._awaiting_work_zero_report = False
        self.work_zero_state_var.set(f"XYZ work zero not confirmed — {reason}")

    def retract_safe_z(self) -> None:
        position = self._current_machine_position()
        if self.status is None or not self.status.can_jog or position is None:
            self._set_action_status("Safe-Z move ignored — GRBL is not Idle with a machine position")
            return
        if not self.envelope.trusted:
            self._set_action_status("Safe-Z move ignored — establish the virtual machine reference first")
            return
        relative = self.envelope.relative_position(position)
        assert relative is not None
        distance = self.profile.safe_z - relative.z
        if abs(distance) < 0.001:
            self._set_action_status("Z is already at the configured safe height")
            return
        allowed, reason = self.envelope.check_jog("Z", distance, position, self.profile)
        if not allowed:
            self._set_action_status(f"Safe-Z move blocked — {reason}")
            return
        if distance < 0 and not messagebox.askyesno(
            "Safe Z is below the current position",
            f"This command would move Z downward {abs(distance):.3f} mm. Continue?",
            icon="warning",
        ):
            return
        try:
            feed = min(float(self.feed_var.get()), 100.0)
            self._send_manual_line(make_jog("Z", distance, feed))
        except (ValueError, RuntimeError) as exc:
            self._set_action_status(f"Safe-Z move not sent — {exc}")

    def return_to_reference(self) -> None:
        self._queue_position_move(
            Position(0.0, 0.0, 0.0),
            "Returning to virtual X0 Y0 Z0 via safe Z",
            "Returned to virtual X0 Y0 Z0 via the configured safe height",
        )

    def return_to_work_zero(self) -> None:
        """Return to the confirmed GRBL work origin via the virtual safe height."""
        position = self._current_machine_position()
        if not self.work_zero_confirmed or self.status is None or self.status.work_offset is None:
            self._skip_work_zero_return("work zero is not confirmed by a fresh GRBL report")
            return
        if not self.envelope.trusted or self.envelope.reference is None or position is None:
            self._skip_work_zero_return("the virtual machine reference is not trusted")
            return
        target = work_zero_virtual_target(self.envelope.reference, self.status.work_offset)
        relative = self.envelope.relative_position(position)
        assert relative is not None
        try:
            plan_safe_position_jogs(relative, target, self.profile)
        except ValueError as exc:
            self._skip_work_zero_return(str(exc))
            return
        self._queue_position_move(
            target,
            "Returning to work X0 Y0 Z0 via safe Z",
            "Returned to work X0 Y0 Z0 via the configured safe height",
        )

    def _skip_work_zero_return(self, reason: str) -> None:
        self._append_system_log(f"Automatic work-zero return skipped: {reason}")
        self._set_action_status(f"Automatic work-zero return skipped — {reason}; retracting to safe Z")
        self.retract_safe_z()

    def jog_to_position(self) -> None:
        try:
            target = Position(*(float(self.position_target_vars[axis].get()) for axis in "XYZ"))
        except (ValueError, tk.TclError):
            self._set_action_status("Position not accepted — enter numeric X, Y, and Z coordinates")
            return
        self._queue_position_move(
            target,
            f"Jogging to virtual X{target.x:g} Y{target.y:g} Z{target.z:g} via safe Z",
            f"Reached virtual X{target.x:g} Y{target.y:g} Z{target.z:g}",
        )

    def _queue_position_move(self, target: Position, starting_message: str, completion_message: str) -> None:
        position = self._current_machine_position()
        if self.job_active:
            self._set_action_status("Position move ignored — an engraving job is active")
            return
        if self._position_move_active or self._pending_manual_acks:
            self._set_action_status("Position move ignored — wait for the current manual command to finish")
            return
        if self.status is None or not self.status.can_jog or position is None:
            self._set_action_status("Position move ignored — GRBL is not Idle with a machine position")
            return
        if not self.envelope.trusted:
            self._set_action_status("Position move ignored — establish the virtual machine reference first")
            return

        relative = self.envelope.relative_position(position)
        assert relative is not None
        try:
            feed = float(self.feed_var.get())
            if not 0 < feed <= 1500:
                raise ValueError("Jog feed must be between 0 and 1500 mm/min")
            planned_moves = plan_safe_position_jogs(relative, target, self.profile)
        except (ValueError, tk.TclError) as exc:
            self._set_action_status(f"Position move blocked — {exc}")
            return

        if not planned_moves:
            self._set_action_status(completion_message)
            return
        self._position_move_queue = [(axis, distance, feed) for axis, distance in planned_moves]
        self._position_move_active = True
        self._position_move_completion = completion_message
        self._set_action_status(starting_message)
        self._refresh_job_ui()
        self._send_next_position_move()

    def _send_next_position_move(self) -> None:
        if not self._position_move_active or self._pending_manual_acks:
            return
        if not self._position_move_queue:
            self._position_move_active = False
            self._set_action_status(self._position_move_completion)
            self._append_system_log(self._position_move_completion)
            self._refresh_job_ui()
            return
        axis, distance, feed = self._position_move_queue.pop(0)
        try:
            self._send_manual_line(make_jog(axis, distance, feed))
        except (ValueError, RuntimeError) as exc:
            self._position_move_queue = []
            self._position_move_active = False
            self._set_action_status(f"Position move stopped — {exc}")
            self._refresh_job_ui()

    def set_work_zero(self, axes: str) -> None:
        if self.status is None or not self.status.can_jog:
            self._set_action_status("Work-zero command ignored — GRBL is not Idle")
            return
        try:
            self.work_offset = None
            self.work_zero_confirmed = False
            self._awaiting_work_zero_report = axes.upper() == "XYZ"
            self.work_zero_state_var.set("Waiting for GRBL to report the updated XYZ work offset…")
            self._send_manual_line(make_work_zero(axes))
        except (ValueError, RuntimeError) as exc:
            self._awaiting_work_zero_report = False
            self.work_zero_state_var.set("XYZ work zero not confirmed")
            self._set_action_status(f"Work zero not sent — {exc}")
        else:
            self._set_action_status(f"Set {axes} work zero requested; waiting for GRBL acknowledgement")

    def realtime(self, command: bytes) -> None:
        try:
            self.connection.send_realtime(command)
        except RuntimeError as exc:
            self._set_action_status(f"Command not sent — {exc}")

    def soft_reset(self) -> None:
        if messagebox.askyesno(
            "Reset GRBL?",
            "This immediately stops motion, resets GRBL, and invalidates the virtual reference. Continue?",
            icon="warning",
        ):
            self.job.abort("GRBL soft reset")
            self._invalidate_work_zero("GRBL soft reset")
            self._pending_manual_acks = 0
            self._position_move_queue = []
            self._position_move_active = False
            self._return_after_job_pending = False
            self._preserve_references_on_next_reset = False
            self.invalidate_reference("GRBL soft reset")
            self.realtime(REALTIME_SOFT_RESET)
            self._refresh_job_ui()

    def _process_events(self) -> None:
        while not self.connection.events.empty():
            self._handle_event(self.connection.events.get_nowait())
        self.after(50, self._process_events)

    def _handle_event(self, event: SerialEvent) -> None:
        self._append_log(event)
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_event(event)
        if event.kind == "rx":
            old_job_state = self.job.state
            response_lower = event.text.strip().lower()
            wifi_response = self._handle_wifi_setup_response(event.text)
            manual_response = not wifi_response and self._pending_manual_acks > 0 and (
                response_lower == "ok" or response_lower.startswith("error:") or response_lower.startswith("alarm:")
            )
            if manual_response:
                self._pending_manual_acks -= 1
                if response_lower != "ok" and self._position_move_active:
                    self._position_move_queue = []
                    self._position_move_active = False
                    self._set_action_status(f"Position move stopped — GRBL replied: {event.text.strip()}")
                    self._refresh_job_ui()
                elif self._position_move_active:
                    self.after(0, self._send_next_position_move)
            handled_by_job = False if wifi_response or manual_response else self.job.handle_response(event.text)
            if handled_by_job:
                self._refresh_job_ui()
            if old_job_state in {"running", "paused"} and self.job.state == "complete":
                self._return_after_job_pending = True
                try:
                    self._send_manual_line(b"M5\n")
                except RuntimeError:
                    self._return_after_job_pending = False
                self._append_system_log("Engraving job completed; spindle stop requested")
                self._set_action_status("Job complete — waiting for Idle, then returning to work zero")
            elif old_job_state in {"running", "paused"} and self.job.state == "failed":
                self._return_after_job_pending = False
                try:
                    self.connection.send_realtime(REALTIME_HOLD)
                    self._send_manual_line(b"M5\n")
                except RuntimeError:
                    pass
                self._append_system_log(f"Engraving job failed: {self.job.error}")
                messagebox.showerror("Job failed", f"GRBL stopped the job:\n\n{self.job.error}")
            address = extract_controller_ip(event.text)
            if address:
                self._adopt_wifi_address(address)
                if self._wifi_discovery_active:
                    self._wifi_discovery_active = False
                    self._wifi_discovery_attempts = 0
                    self._wifi_setup_commands = []
                    self._log_redactions.clear()
                    self.connection_var.set(f"Controller joined the LAN at {address}; Wi-Fi TCP settings saved")
                    messagebox.showinfo(
                        "Controller Wi-Fi connected",
                        f"The controller joined the network at {address}. Disconnect USB, select Wi-Fi TCP, and connect.",
                    )
            if event.text.startswith("Grbl ") or "[MSG:Reset" in event.text:
                self._pending_manual_acks = 0
                self._position_move_queue = []
                self._position_move_active = False
                self._return_after_job_pending = False
                if self._preserve_references_on_next_reset:
                    self._preserve_references_on_next_reset = False
                    self._append_system_log("GRBL reset acknowledged after controlled abort; virtual reference and work zero retained")
                    self._set_action_status("Job aborted — virtual reference and work zero retained")
                else:
                    self._invalidate_work_zero("controller startup/reset detected")
                    self.invalidate_reference("Controller startup/reset detected")
            status = parse_status(event.text)
            if status is not None:
                self.status = status
                if status.work_offset is not None:
                    self.work_offset = status.work_offset
                    if self._awaiting_work_zero_report:
                        self.work_zero_confirmed = True
                        self._awaiting_work_zero_report = False
                        self.work_zero_state_var.set("XYZ work zero confirmed for this session")
                self._show_status(status)
                if (
                    self._return_after_job_pending
                    and status.can_jog
                    and self._pending_manual_acks == 0
                    and not self._position_move_active
                ):
                    self._return_after_job_pending = False
                    self.after(0, self.return_to_work_zero)
        elif event.kind == "error":
            self.job.abort(f"Connection error: {event.text}")
            self.invalidate_reference("Serial error")
            self.connection.disconnect()
            self._disconnected_ui()
            self.connection_var.set(f"Connection error: {event.text}")
            self._refresh_job_ui()

    def _show_status(self, status: GrblStatus) -> None:
        self.state_var.set(status.state)
        self.connection_var.set(f"Connected — GRBL {status.state}")
        self.feed_actual_var.set(f"{status.feed:g}" if status.feed is not None else "—")
        self.spindle_var.set(f"{status.spindle:g}" if status.spindle is not None else "—")
        self.pins_var.set(status.pins or "None")
        if status.machine_position:
            self._show_position(self.machine_position_vars, status.machine_position)
            self._show_position_summary(self.machine_position_summary_var, "M", status.machine_position)
        work_position = status.work_position
        if work_position is None and status.machine_position is not None and self.work_offset is not None:
            work_position = status.machine_position.minus(self.work_offset)
        if work_position:
            self._show_position(self.work_position_vars, work_position)
            self._show_position_summary(self.work_position_summary_var, "W", work_position)
        if status.machine_position and self.envelope.trusted:
            relative = self.envelope.relative_position(status.machine_position)
            if relative:
                self._show_position(self.reference_position_vars, relative)
                self._show_position_summary(self.reference_position_summary_var, "V", relative)
        self._set_motion_controls(
            self.connection.connected and not self.job_active and not self._position_move_active
        )
        self.job_panel.update_controls()
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_status(status)

    @staticmethod
    def _show_position(variables: dict[str, tk.StringVar], position: Position) -> None:
        for axis, value in zip("XYZ", (position.x, position.y, position.z)):
            variables[axis].set(f"{value:.3f}")

    @staticmethod
    def _show_position_summary(variable: tk.StringVar, prefix: str, position: Position) -> None:
        variable.set(f"{prefix}  X{position.x:.2f}  Y{position.y:.2f}  Z{position.z:.2f}")

    def _show_reference_state(self) -> None:
        if self.envelope.trusted:
            self.reference_var.set("POSITION TRUSTED — virtual limits active")
            self.reference_label.configure(style="Trusted.TLabel")
            position = self._current_machine_position()
            if position:
                relative = self.envelope.relative_position(position)
                if relative:
                    self._show_position(self.reference_position_vars, relative)
        else:
            self.reference_var.set(f"POSITION UNKNOWN — {self.envelope.invalid_reason}")
            self.reference_label.configure(style="Unknown.TLabel")
            for variable in self.reference_position_vars.values():
                variable.set("—")
            self.reference_position_summary_var.set("V  X—  Y—  Z—")

    def _poll_status(self) -> None:
        if self.connection.connected:
            try:
                self.connection.send_realtime(REALTIME_STATUS)
            except RuntimeError:
                pass
        self.after(self.POLL_MS, self._poll_status)

    def _update_controls_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all"))

    def _fit_controls_to_canvas(self, event: tk.Event[tk.Misc]) -> None:
        self.controls_canvas.itemconfigure(self._controls_canvas_window, width=event.width)

    def _scroll_controls_with_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        pointer_x = self.winfo_pointerx() - self.controls_canvas.winfo_rootx()
        pointer_y = self.winfo_pointery() - self.controls_canvas.winfo_rooty()
        over_controls = 0 <= pointer_x < self.controls_canvas.winfo_width() and 0 <= pointer_y < self.controls_canvas.winfo_height()
        if over_controls and event.delta:
            self.controls_canvas.yview_scroll(-int(event.delta / 120), "units")

    def _append_system_log(self, text: str) -> None:
        self._append_log(SerialEvent("system", text, datetime.now()))

    def _set_action_status(self, text: str, clear_ms: int = 8000) -> None:
        self._action_status_revision += 1
        revision = self._action_status_revision
        self.action_status_var.set(text)

        def clear() -> None:
            if revision == self._action_status_revision:
                self.action_status_var.set("Ready")

        self.after(clear_ms, clear)

    def _append_log(self, event: SerialEvent) -> None:
        safe_text = event.text
        for secret in self._log_redactions:
            if secret:
                safe_text = safe_text.replace(secret, "<redacted>")
        line = f"{event.timestamp:%H:%M:%S.%f}"[:-3] + f"  {event.kind:11}  {safe_text}\n"
        with self.log_file.open("a", encoding="utf-8") as stream:
            stream.write(line)
        self.log.configure(state="normal")
        self.log.insert("end", line)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_motion_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for control in self.motion_controls:
            control.configure(state=state)

    def _disconnected_ui(self) -> None:
        self.job.abort("Disconnected")
        self._pending_manual_acks = 0
        self._position_move_queue = []
        self._position_move_active = False
        self._return_after_job_pending = False
        self._preserve_references_on_next_reset = False
        self.invalidate_reference("Disconnected; physical position cannot be guaranteed")
        self.status = None
        self.work_offset = None
        self._invalidate_work_zero("disconnected")
        self.connect_button.configure(text="Connect")
        self._update_connection_action_buttons()
        self.connection_var.set("Disconnected")
        self.state_var.set("Unknown")
        self._set_motion_controls(False)
        self._update_transport_fields()
        self._refresh_job_ui()
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_connection_changed()

    def close(self) -> None:
        if self.connection.connected:
            self.connection.disconnect()
        self.destroy()


def main() -> None:
    ControllerApp().mainloop()
