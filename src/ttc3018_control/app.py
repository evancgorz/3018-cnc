from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

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
from .machine_state import MachineProfile, ProfileStore, VirtualEnvelope
from .serial_connection import GrblConnection, SerialEvent, available_ports
from .tcp_connection import TcpGrblConnection


class ControllerApp(tk.Tk):
    POLL_MS = 500

    def __init__(self) -> None:
        super().__init__()
        self.title("TTC 3018 Control — Reference & Safety")
        self.geometry("1160x820")
        self.minsize(1000, 720)

        self.connection = GrblConnection()
        self.status: GrblStatus | None = None
        self.work_offset: Position | None = None
        self.envelope = VirtualEnvelope()
        self.unreferenced_jog_acknowledged = False
        self._log_redactions: set[str] = set()
        self.log_file = self._new_log_file()
        self.profile_store = ProfileStore(Path.cwd() / "config" / "machine-profile.json")
        self.connection_settings_store = ConnectionSettingsStore(Path.cwd() / "config" / "connection.json")
        self.commissioning_store = CommissioningStore(Path.cwd() / "config" / "commissioning.json")
        self.commissioning_window: CommissioningWindow | None = None
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
        self.feed_actual_var = tk.StringVar(value="0")
        self.spindle_var = tk.StringVar(value="0")
        self.pins_var = tk.StringVar(value="—")
        self.reference_var = tk.StringVar(value="POSITION UNKNOWN — virtual limits inactive")
        self.step_var = tk.DoubleVar(value=1.0)
        self.feed_var = tk.DoubleVar(value=100.0)
        self.profile_name_var = tk.StringVar(value=self.profile.name)
        self.travel_vars = {
            "X": tk.StringVar(value=self._profile_value(self.profile.travel_x)),
            "Y": tk.StringVar(value=self._profile_value(self.profile.travel_y)),
            "Z": tk.StringVar(value=self._profile_value(self.profile.travel_z)),
        }
        self.safe_z_var = tk.StringVar(value=self._profile_value(self.profile.safe_z))
        self.motion_controls: list[ttk.Button] = []

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
        style = ttk.Style(self)
        style.configure("Trusted.TLabel", foreground="#087a2f", font=("Segoe UI", 10, "bold"))
        style.configure("Unknown.TLabel", foreground="#a05a00", font=("Segoe UI", 10, "bold"))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        connection = ttk.LabelFrame(self, text="Connection", padding=10)
        connection.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="Transport").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.transport_combo = ttk.Combobox(
            connection,
            textvariable=self.transport_var,
            values=("USB serial", "Wi-Fi TCP"),
            state="readonly",
            width=18,
        )
        self.transport_combo.grid(row=0, column=1, sticky="w")
        self.transport_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_transport_fields())
        self.wifi_setup_button = ttk.Button(
            connection,
            text="Wi-Fi Setup…",
            command=self.configure_house_wifi,
        )
        self.wifi_setup_button.grid(row=0, column=2, padx=8)
        self.connect_button = ttk.Button(connection, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=3, sticky="e")

        ttk.Label(connection, text="USB serial port").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, state="readonly", width=42)
        self.port_combo.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.refresh_button = ttk.Button(connection, text="Refresh", command=self.refresh_ports)
        self.refresh_button.grid(row=1, column=2, padx=8, pady=(6, 0))
        ttk.Button(connection, text="Commissioning…", command=self.open_commissioning).grid(
            row=1, column=3, sticky="e", pady=(6, 0)
        )

        ttk.Label(connection, text="Wi-Fi host").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self.wifi_host_entry = ttk.Entry(connection, textvariable=self.wifi_host_var)
        self.wifi_host_entry.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(connection, text="TCP port").grid(row=2, column=2, sticky="e", padx=(8, 4), pady=(6, 0))
        self.wifi_port_entry = ttk.Spinbox(connection, from_=1, to=65535, textvariable=self.wifi_port_var, width=8)
        self.wifi_port_entry.grid(row=2, column=3, sticky="e", pady=(6, 0))
        ttk.Label(connection, textvariable=self.connection_var).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        dashboard = ttk.Frame(self, padding=(10, 5))
        dashboard.grid(row=1, column=0, sticky="ew")
        dashboard.columnconfigure(0, weight=1)
        dashboard.columnconfigure(1, weight=2)
        state_panel = ttk.LabelFrame(dashboard, text="Live GRBL state", padding=10)
        state_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        state_panel.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate(
            [
                ("State", self.state_var),
                ("Feed (mm/min)", self.feed_actual_var),
                ("Spindle command", self.spindle_var),
                ("Active input pins", self.pins_var),
            ]
        ):
            ttk.Label(state_panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16))
            ttk.Label(state_panel, textvariable=variable).grid(row=row, column=1, sticky="w")

        position = ttk.LabelFrame(dashboard, text="Coordinates (mm)", padding=10)
        position.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ttk.Label(position, text="Coordinate").grid(row=0, column=0, sticky="w")
        for column, axis in enumerate("XYZ", start=1):
            ttk.Label(position, text=axis, font=("Segoe UI", 10, "bold")).grid(row=0, column=column, padx=25)
        for row, (label, variables) in enumerate(
            [
                ("GRBL machine", self.machine_position_vars),
                ("GRBL work", self.work_position_vars),
                ("Virtual reference", self.reference_position_vars),
            ],
            start=1,
        ):
            ttk.Label(position, text=label).grid(row=row, column=0, sticky="w", pady=2)
            for column, axis in enumerate("XYZ", start=1):
                ttk.Label(position, textvariable=variables[axis], font=("Consolas", 13)).grid(
                    row=row, column=column, padx=25, pady=2
                )

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))
        controls = ttk.Frame(body, padding=(0, 0, 8, 0))
        body.add(controls, weight=2)
        controls.columnconfigure(0, weight=1)

        motion = ttk.LabelFrame(controls, text="Guarded jog controls", padding=10)
        motion.grid(row=0, column=0, sticky="ew")
        ttk.Label(motion, text="Step (mm)").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            motion,
            textvariable=self.step_var,
            values=(0.1, 1.0, 5.0, 10.0, 20.0),
            state="readonly",
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(motion, text="Feed (mm/min)").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Spinbox(motion, from_=1, to=1500, textvariable=self.feed_var, width=11).grid(row=1, column=1, sticky="w", padx=8)
        jogs = ttk.Frame(motion)
        jogs.grid(row=2, column=0, columnspan=4, pady=8)
        for text, axis, sign, row, column in [
            ("Y +", "Y", 1, 0, 1),
            ("X −", "X", -1, 1, 0),
            ("X +", "X", 1, 1, 2),
            ("Y −", "Y", -1, 2, 1),
            ("Z + (up)", "Z", 1, 0, 3),
            ("Z − (down)", "Z", -1, 1, 3),
        ]:
            button = ttk.Button(jogs, text=text, command=lambda a=axis, s=sign: self.jog(a, s), width=13)
            button.grid(row=row, column=column, padx=4, pady=4)
            self.motion_controls.append(button)
        actions = ttk.Frame(motion)
        actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        for column, (text, command) in enumerate(
            [
                ("Feed hold", lambda: self.realtime(REALTIME_HOLD)),
                ("Resume", lambda: self.realtime(REALTIME_RESUME)),
                ("Cancel jog", lambda: self.realtime(REALTIME_JOG_CANCEL)),
            ]
        ):
            button = ttk.Button(actions, text=text, command=command)
            button.grid(row=0, column=column, padx=3, sticky="ew")
            actions.columnconfigure(column, weight=1)
            self.motion_controls.append(button)

        reference = ttk.LabelFrame(controls, text="Reference and virtual envelope", padding=10)
        reference.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        reference.columnconfigure(1, weight=1)
        ttk.Label(reference, text="Machine name").grid(row=0, column=0, sticky="w")
        ttk.Entry(reference, textvariable=self.profile_name_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        for row, axis in enumerate("XYZ", start=1):
            ttk.Label(reference, text=f"{axis} travel (mm)").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(reference, textvariable=self.travel_vars[axis], width=10).grid(row=row, column=1, sticky="w", padx=8)
        ttk.Label(reference, text="Safe Z (from reference)").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(reference, textvariable=self.safe_z_var, width=10).grid(row=4, column=1, sticky="w", padx=8)
        ttk.Button(reference, text="Save profile", command=self.save_profile).grid(row=1, column=2, rowspan=2, sticky="nsew", padx=(8, 0))
        self.reference_label = ttk.Label(reference, textvariable=self.reference_var, style="Unknown.TLabel")
        self.reference_label.grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 6))
        establish = ttk.Button(reference, text="Establish reference here…", command=self.establish_reference)
        establish.grid(row=6, column=0, columnspan=2, sticky="ew", padx=(0, 4))
        invalidate = ttk.Button(reference, text="Invalidate", command=lambda: self.invalidate_reference("Manually invalidated"))
        invalidate.grid(row=6, column=2, sticky="ew", padx=4)
        safe_z = ttk.Button(reference, text="Retract to safe Z", command=self.retract_safe_z)
        safe_z.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.motion_controls.extend([establish, invalidate, safe_z])

        work_zero = ttk.LabelFrame(controls, text="Work zero (does not move the machine)", padding=10)
        work_zero.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for column, axes in enumerate(("X", "Y", "Z", "XYZ")):
            button = ttk.Button(work_zero, text=f"Zero {axes}", command=lambda a=axes: self.set_work_zero(a))
            button.grid(row=0, column=column, sticky="ew", padx=3)
            work_zero.columnconfigure(column, weight=1)
            self.motion_controls.append(button)
        reset = ttk.Button(work_zero, text="Soft reset…", command=self.soft_reset)
        reset.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.motion_controls.append(reset)

        log_frame = ttk.LabelFrame(body, text="Communication log", padding=8)
        body.add(log_frame, weight=3)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, state="disabled", wrap="none", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        ttk.Label(log_frame, text=f"Saved to {self.log_file}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._set_motion_controls(False)

    def refresh_ports(self) -> None:
        ports = available_ports()
        labels = [f"{device} — {description}" for device, description in ports]
        self.port_combo["values"] = labels
        preferred = next((label for label in labels if label.startswith("COM3 ")), None)
        if preferred:
            self.port_var.set(preferred)
        elif labels:
            self.port_var.set(labels[0])

    def open_commissioning(self) -> None:
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.lift()
            self.commissioning_window.focus_force()
            return
        self.commissioning_window = CommissioningWindow(self, self.commissioning_store)

    def _update_transport_fields(self) -> None:
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
                host = self.wifi_host_var.get().strip()
                tcp_port = int(self.wifi_port_var.get())
                connection = TcpGrblConnection()
                connection.connect(host, tcp_port)
                endpoint = f"{host}:{tcp_port} over Wi-Fi"
        except (OSError, ValueError, RuntimeError) as exc:
            detail = str(exc)
            if self.transport_var.get() == "Wi-Fi TCP":
                detail = (
                    f"Could not reach {self.wifi_host_var.get().strip()}:{self.wifi_port_var.get()}.\n\n"
                    "Confirm the controller and PC are on the same network. If its DHCP address changed, connect by USB "
                    "and open Wi-Fi Setup so the app can rediscover it.\n\n"
                    f"Technical detail: {detail}"
                )
            messagebox.showerror("Connection failed", detail)
            return
        self.connection = connection
        if self.transport_var.get() == "Wi-Fi TCP":
            self._save_connection_settings(host, tcp_port, preferred_transport="Wi-Fi TCP")
        self.connect_button.configure(text="Disconnect")
        self.connection_var.set(f"Connected to {endpoint}; waiting for GRBL status")
        self._update_transport_fields()

    def configure_house_wifi(self) -> None:
        if not self.connection.connected or not isinstance(self.connection, GrblConnection):
            messagebox.showwarning("USB required", "Connect through USB before configuring controller Wi-Fi.")
            return
        if self.status is None or not self.status.can_jog:
            messagebox.showwarning("Controller not ready", "Wait for GRBL to report Idle before changing Wi-Fi mode.")
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
                ssid_bytes = ssid.encode("ascii")
                password_bytes = password.encode("ascii")
            except UnicodeEncodeError:
                messagebox.showerror("Unsupported characters", "Use ASCII characters for the SSID and password.", parent=dialog)
                return
            if not ssid or any(character in ssid for character in "]\r\n"):
                messagebox.showerror("Invalid network name", "Enter a valid network name.", parent=dialog)
                return
            if not 8 <= len(password_bytes) <= 63 or any(character in password for character in "]\r\n"):
                messagebox.showerror("Invalid password", "A WPA/WPA2 password must contain 8 to 63 characters.", parent=dialog)
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
            commands = [
                (b"[ESP100]" + ssid_bytes, "[ESP100]<SSID redacted>"),
                (b"[ESP101]" + password_bytes, "[ESP101]<password redacted>"),
                (b"[ESP110]STA", "[ESP110]STA"),
                (b"[ESP115]ON", "[ESP115]ON"),
                (b"[ESP444]RESTART", "[ESP444]RESTART"),
            ]
            self.invalidate_reference("Controller Wi-Fi reconfiguration")
            self.connection_var.set("Configuring controller Wi-Fi; controller will restart…")
            self._send_wifi_setup_commands(commands, 0)

        ttk.Button(buttons, text="Configure", command=submit).grid(row=0, column=1)
        ssid_entry.focus_set()
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _send_wifi_setup_commands(self, commands: list[tuple[bytes, str]], index: int) -> None:
        if index >= len(commands):
            self.connection_var.set("Wi-Fi settings sent; waiting for controller restart and LAN address…")
            self.after(10000, self._request_controller_identity)
            return
        if not self.connection.connected:
            messagebox.showerror("Wi-Fi setup interrupted", "The USB connection closed before setup completed.")
            return
        command, display_text = commands[index]
        try:
            self.connection.send_line(command, display_text=display_text)
        except RuntimeError as exc:
            messagebox.showerror("Wi-Fi setup interrupted", str(exc))
            return
        self.after(400, lambda: self._send_wifi_setup_commands(commands, index + 1))

    def _request_controller_identity(self) -> None:
        if self.connection.connected and isinstance(self.connection, GrblConnection):
            try:
                self.connection.send_line(b"$I")
            except RuntimeError:
                pass
        self.after(5000, self._log_redactions.clear)

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

    def jog(self, axis: str, sign: int) -> None:
        if self.status is None or not self.status.can_jog:
            messagebox.showwarning("Jog blocked", "GRBL must report Idle before a jog can be sent.")
            return
        position = self._current_machine_position()
        if position is None:
            messagebox.showwarning("Jog blocked", "A machine-position report is required before jogging.")
            return
        try:
            distance = float(self.step_var.get()) * sign
            feed = float(self.feed_var.get())
            if self.envelope.trusted:
                allowed, reason = self.envelope.check_jog(axis, distance, position, self.profile)
                if not allowed:
                    messagebox.showwarning("Virtual limit", reason)
                    return
            elif not self.unreferenced_jog_acknowledged:
                if not messagebox.askyesno(
                    "Virtual limits inactive",
                    "The physical position is not referenced, so virtual limits cannot protect this jog. "
                    "Allow unreferenced jogging for this connection session?",
                    icon="warning",
                ):
                    return
                self.unreferenced_jog_acknowledged = True
            self.connection.send_line(make_jog(axis, distance, feed))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Jog not sent", str(exc))

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
            messagebox.showerror("Profile not saved", str(exc))
            return
        self.profile = profile
        if self.envelope.trusted:
            self.invalidate_reference("Profile changed; establish the reference again")
        messagebox.showinfo("Profile saved", "Travel and safe-Z settings were saved. No GRBL settings were changed.")

    def establish_reference(self) -> None:
        position = self._current_machine_position()
        if self.status is None or not self.status.can_jog or position is None:
            messagebox.showwarning("Cannot establish reference", "Connect and wait for GRBL to report Idle with a machine position.")
            return
        try:
            self.profile.validate()
        except ValueError as exc:
            messagebox.showerror("Profile required", f"Save a valid machine profile first.\n\n{exc}")
            return
        if not messagebox.askyesno(
            "Establish virtual reference?",
            "The current physical position will become virtual X0, Y0, Z0. Protection will assume all allowed travel "
            "is in the positive direction from here.\n\nUse this only when the machine is positioned near its chosen X−, Y−, and Z− reference.",
            icon="warning",
        ):
            return
        self.envelope.establish(position, self.profile)
        self.unreferenced_jog_acknowledged = False
        self._show_reference_state()
        self._append_system_log("Virtual reference established at current GRBL machine position")

    def invalidate_reference(self, reason: str) -> None:
        was_trusted = self.envelope.trusted
        self.envelope.invalidate(reason)
        self.unreferenced_jog_acknowledged = False
        self._show_reference_state()
        if was_trusted:
            self._append_system_log(f"Virtual reference invalidated: {reason}")

    def retract_safe_z(self) -> None:
        position = self._current_machine_position()
        if self.status is None or not self.status.can_jog or position is None:
            messagebox.showwarning("Retract blocked", "GRBL must report Idle with a machine position.")
            return
        if not self.envelope.trusted:
            messagebox.showwarning("Retract blocked", "Establish a trusted virtual reference first.")
            return
        relative = self.envelope.relative_position(position)
        assert relative is not None
        distance = self.profile.safe_z - relative.z
        if abs(distance) < 0.001:
            messagebox.showinfo("Safe Z", "Z is already at the configured safe height.")
            return
        allowed, reason = self.envelope.check_jog("Z", distance, position, self.profile)
        if not allowed:
            messagebox.showwarning("Retract blocked", reason)
            return
        if distance < 0 and not messagebox.askyesno(
            "Safe Z is below the current position",
            f"This command would move Z downward {abs(distance):.3f} mm. Continue?",
            icon="warning",
        ):
            return
        try:
            feed = min(float(self.feed_var.get()), 100.0)
            self.connection.send_line(make_jog("Z", distance, feed))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Retract not sent", str(exc))

    def set_work_zero(self, axes: str) -> None:
        if self.status is None or not self.status.can_jog:
            messagebox.showwarning("Work zero blocked", "GRBL must report Idle.")
            return
        if not messagebox.askyesno(
            f"Set {axes} work zero?",
            f"Set the current position as work zero for {axes}? This changes the GRBL work-coordinate offset but does not move the machine.",
        ):
            return
        try:
            self.connection.send_line(make_work_zero(axes))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Work zero not sent", str(exc))

    def realtime(self, command: bytes) -> None:
        try:
            self.connection.send_realtime(command)
        except RuntimeError as exc:
            messagebox.showerror("Command not sent", str(exc))

    def soft_reset(self) -> None:
        if messagebox.askyesno(
            "Reset GRBL?",
            "This immediately stops motion, resets GRBL, and invalidates the virtual reference. Continue?",
            icon="warning",
        ):
            self.invalidate_reference("GRBL soft reset")
            self.realtime(REALTIME_SOFT_RESET)

    def _process_events(self) -> None:
        while not self.connection.events.empty():
            self._handle_event(self.connection.events.get_nowait())
        self.after(50, self._process_events)

    def _handle_event(self, event: SerialEvent) -> None:
        self._append_log(event)
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_event(event)
        if event.kind == "rx":
            address = extract_controller_ip(event.text)
            if address:
                self._adopt_wifi_address(address)
            if event.text.startswith("Grbl ") or "[MSG:Reset" in event.text:
                self.invalidate_reference("Controller startup/reset detected")
            status = parse_status(event.text)
            if status is not None:
                self.status = status
                if status.work_offset is not None:
                    self.work_offset = status.work_offset
                self._show_status(status)
        elif event.kind == "error":
            self.invalidate_reference("Serial error")
            self.connection.disconnect()
            self._disconnected_ui()
            self.connection_var.set(f"Connection error: {event.text}")

    def _show_status(self, status: GrblStatus) -> None:
        self.state_var.set(status.state)
        self.connection_var.set(f"Connected — GRBL {status.state}")
        self.feed_actual_var.set(f"{status.feed:g}" if status.feed is not None else "—")
        self.spindle_var.set(f"{status.spindle:g}" if status.spindle is not None else "—")
        self.pins_var.set(status.pins or "None")
        if status.machine_position:
            self._show_position(self.machine_position_vars, status.machine_position)
        work_position = status.work_position
        if work_position is None and status.machine_position is not None and self.work_offset is not None:
            work_position = status.machine_position.minus(self.work_offset)
        if work_position:
            self._show_position(self.work_position_vars, work_position)
        if status.machine_position and self.envelope.trusted:
            relative = self.envelope.relative_position(status.machine_position)
            if relative:
                self._show_position(self.reference_position_vars, relative)
        self._set_motion_controls(self.connection.connected)
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_status(status)

    @staticmethod
    def _show_position(variables: dict[str, tk.StringVar], position: Position) -> None:
        for axis, value in zip("XYZ", (position.x, position.y, position.z)):
            variables[axis].set(f"{value:.3f}")

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

    def _poll_status(self) -> None:
        if self.connection.connected:
            try:
                self.connection.send_realtime(REALTIME_STATUS)
            except RuntimeError:
                pass
        self.after(self.POLL_MS, self._poll_status)

    def _append_system_log(self, text: str) -> None:
        self._append_log(SerialEvent("system", text, datetime.now()))

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
        self.invalidate_reference("Disconnected; physical position cannot be guaranteed")
        self.status = None
        self.work_offset = None
        self.connect_button.configure(text="Connect")
        self.connection_var.set("Disconnected")
        self.state_var.set("Unknown")
        self._set_motion_controls(False)
        self._update_transport_fields()
        if self.commissioning_window is not None and self.commissioning_window.winfo_exists():
            self.commissioning_window.on_connection_changed()

    def close(self) -> None:
        if self.connection.connected:
            self.connection.disconnect()
        self.destroy()


def main() -> None:
    ControllerApp().mainloop()
