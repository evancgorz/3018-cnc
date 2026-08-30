from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

from .machine_state import MachineProfile

if TYPE_CHECKING:
    from .app import ControllerApp


class SetupWizard(tk.Toplevel):
    """Guided, state-gated manual setup and engraving workflow."""

    STEP_TITLES = (
        "Understand manual operation",
        "Connect to the controller",
        "Calibrate the machine profile",
        "Establish the manual machine reference",
        "Set the engraving work zero",
        "Load the pre-sliced G-code",
        "Review the toolpath and machine fit",
        "Complete the physical preflight",
        "Start the engraving job",
    )

    def __init__(self, app: ControllerApp) -> None:
        super().__init__(app)
        self.app = app
        self.index = 0
        self.title("Guided Wizard Mode — Manual Setup & Engraving")
        self.geometry("760x690")
        self.minsize(680, 620)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.understood_var = tk.BooleanVar(value=False)
        self.preview_reviewed_var = tk.BooleanVar(value=False)
        self.material_secure_var = tk.BooleanVar(value=False)
        self.tool_secure_var = tk.BooleanVar(value=False)
        self.power_ready_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()

        shell = ttk.Frame(self, padding=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(shell, variable=self.progress_var, maximum=len(self.STEP_TITLES)).grid(
            row=0, column=0, sticky="ew"
        )
        self.heading = ttk.Label(shell, font=("Segoe UI", 17, "bold"))
        self.heading.grid(row=1, column=0, sticky="w", pady=(12, 8))
        self.content = ttk.Frame(shell)
        self.content.grid(row=2, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)

        footer = ttk.Frame(shell)
        footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        footer.columnconfigure(1, weight=1)
        self.back_button = ttk.Button(footer, text="Back", command=self.back)
        self.back_button.grid(row=0, column=0)
        ttk.Label(footer, textvariable=self.status_var, wraplength=410).grid(row=0, column=1, padx=12, sticky="w")
        self.next_button = ttk.Button(footer, text="Next", command=self.next)
        self.next_button.grid(row=0, column=2)

        self.render()
        self.after(300, self._refresh)

    def _clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _text(self, text: str, *, muted: bool = False) -> None:
        ttk.Label(
            self.content,
            text=text,
            wraplength=690,
            justify="left",
            foreground="#555555" if muted else "",
        ).pack(fill="x", anchor="w", pady=(0, 10))

    def _section(self, title: str, text: str) -> None:
        ttk.Label(self.content, text=title, font=("Segoe UI", 10, "bold")).pack(fill="x", anchor="w")
        self._text(text)

    def _action(self, text: str, command: Callable[[], None]) -> ttk.Button:
        button = ttk.Button(self.content, text=text, command=command)
        button.pack(fill="x", pady=(8, 6))
        return button

    def render(self) -> None:
        self._clear()
        self.heading.configure(text=f"Step {self.index + 1} of {len(self.STEP_TITLES)} — {self.STEP_TITLES[self.index]}")
        self.progress_var.set(self.index + 1)
        self.back_button.configure(state="normal" if self.index else "disabled")
        self.next_button.configure(text="Next", command=self.next)

        renderers = (
            self._welcome,
            self._connection,
            self._profile,
            self._machine_reference,
            self._work_zero,
            self._load_job,
            self._review,
            self._preflight,
            self._run,
        )
        renderers[self.index]()
        self._update_gate()

    def _welcome(self) -> None:
        self._section(
            "What this mode does",
            "The wizard takes you through every state the application needs before it can safely send an engraving job. "
            "It explains each coordinate system and checks the controller state as you proceed.",
        )
        self._section(
            "Why manual setup is required",
            "This machine currently has no commissioned home switches or probe. It cannot discover its physical location. "
            "You must establish the machine reference and material work zero again after every disconnect, reset, power loss, "
            "stall, or manual movement.",
        )
        self._section(
            "Physical emergency stop",
            "Software controls cannot replace physical power removal. Keep clear of the spindle and keep the machine's power "
            "switch or emergency cutoff within immediate reach whenever motion is possible.",
        )
        ttk.Checkbutton(
            self.content,
            text="I understand that this is manual referencing and that I remain responsible for stopping unsafe motion.",
            variable=self.understood_var,
            command=self._update_gate,
        ).pack(fill="x", pady=10)

    def _connection(self) -> None:
        self._section(
            "What connection establishes",
            "A persistent USB or Wi-Fi connection lets the application read GRBL state and coordinates and receive an "
            "acknowledgement for every command.",
        )
        self._section(
            "Why Idle matters",
            "The wizard will not proceed until GRBL reports Idle with a machine-position report. Alarm, Hold, Run, and unknown "
            "states are not safe starting points for manual setup.",
        )
        self._action("Connect / disconnect using the main-window settings", self.app.toggle_connection)
        ttk.Label(self.content, textvariable=self.app.connection_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=8)
        self._text("Choose USB serial or Wi-Fi TCP in the main window before selecting Connect.", muted=True)

    def _profile(self) -> None:
        self._section(
            "What the machine profile establishes",
            "Measured travel defines the temporary software envelope. Safe Z is a known clearance height measured upward from "
            "the manual machine reference.",
        )
        self._section(
            "Why accurate values matter",
            "The application uses these numbers to reject jogs and complete jobs that would leave the usable machine area. "
            "Overstated travel can permit a crash; understated travel only blocks usable space.",
        )
        form = ttk.LabelFrame(self.content, text="Measured machine values (mm)", padding=10)
        form.pack(fill="x", pady=6)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Machine name").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.app.profile_name_var).grid(row=0, column=1, sticky="ew", padx=8)
        for row, axis in enumerate("XYZ", start=1):
            ttk.Label(form, text=f"{axis} usable travel").grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=self.app.travel_vars[axis], width=12).grid(row=row, column=1, sticky="w", padx=8)
        ttk.Label(form, text="Safe Z").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.app.safe_z_var, width=12).grid(row=4, column=1, sticky="w", padx=8)
        self._action("Validate and save machine profile", self.app.save_profile)

    def _machine_reference(self) -> None:
        self._section(
            "What the machine reference means",
            "The current physical location becomes virtual machine X0 Y0 Z0. The software assumes all usable travel extends "
            "in the positive direction from that point. This does not change the engraving file's work coordinates.",
        )
        self._section(
            "How to establish it",
            "With the spindle off, use small, slow jogs in the main window to approach the chosen X-negative, Y-negative, and "
            "Z-negative physical limits. Do not drive into a hard stop. Then establish the reference at the current position.",
        )
        self._action("Establish virtual machine reference here…", self.app.establish_reference)
        ttk.Label(self.content, textvariable=self.app.reference_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=8)
        self._text("A disconnect or reset automatically invalidates this reference.", muted=True)

    def _work_zero(self) -> None:
        self._section(
            "What work zero means",
            "Work zero is the origin used by the engraving file. It is independent of the machine reference. X/Y is commonly a "
            "material corner or center; Z0 is commonly the material surface.",
        )
        self._section(
            "Why it matters",
            "Every coordinate in the file is interpreted relative to this point. An incorrect Z0 can cut too deeply; an incorrect "
            "X/Y zero can move the tool outside the material or machine envelope.",
        )
        self._text("Jog carefully to the intended engraving origin, then set all three work axes to zero.")
        self._action("Set current position as XYZ work zero…", lambda: self.app.set_work_zero("XYZ"))
        ttk.Label(self.content, textvariable=self.app.work_zero_state_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=8)

    def _load_job(self) -> None:
        self._section(
            "What loading does",
            "The application validates the pre-sliced file before any of its commands are sent. It calculates XYZ bounds and "
            "constructs an XY preview.",
        )
        self._section(
            "What is rejected",
            "The MVP accepts metric G0/G1 motion and I/J-form G2/G3 arcs. It rejects inch mode, probing, automatic homing, tool "
            "changes, coordinate-reference changes, R-form arcs, and unknown commands.",
        )
        self._action("Load and validate G-code…", self.app.job_panel.load)
        self._action("Create text engraving…", self.app.open_text_engraver)
        ttk.Label(self.content, textvariable=self.app.job_panel.file_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=6)
        ttk.Label(self.content, textvariable=self.app.job_panel.summary_var, wraplength=680).pack(anchor="w")

    def _review(self) -> None:
        self._section(
            "What to review",
            "Inspect the green cutting path, gray rapid moves, work origin, dimensions, and Z range in the main window. Confirm "
            "that they match the intended engraving orientation and scale.",
        )
        fits, reason = self._fit_status()
        ttk.Label(
            self.content,
            text=("PASS — " if fits else "BLOCKED — ") + reason,
            wraplength=680,
            foreground="#087a2f" if fits else "#9b3b00",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=12)
        ttk.Checkbutton(
            self.content,
            text="I reviewed the preview, dimensions, orientation, rapid moves, and cutting-depth range.",
            variable=self.preview_reviewed_var,
            command=self._update_gate,
        ).pack(fill="x", pady=8)

    def _preflight(self) -> None:
        self._section(
            "Why this cannot be automated",
            "Software cannot see a loose workpiece, incorrectly installed tool, forgotten wrench, obstruction, or inaccessible "
            "power switch. These physical checks are required immediately before motion.",
        )
        for text, variable in (
            ("The material is firmly secured and the planned path is unobstructed.", self.material_secure_var),
            ("The correct tool is securely installed and clear of clamps and fixtures.", self.tool_secure_var),
            ("I can immediately cut physical power if motion or spindle behavior is wrong.", self.power_ready_var),
        ):
            ttk.Checkbutton(self.content, text=text, variable=variable, command=self._update_gate).pack(
                fill="x", anchor="w", pady=7
            )
        self._text(
            "For the first test, remove the cutting tool or disconnect spindle power and use the supplied air-cut file.",
            muted=True,
        )

    def _run(self) -> None:
        self._section(
            "Final control",
            "Starting a job sends one command and waits for GRBL's acknowledgement before sending the next. Pause is resumable. "
            "Abort resets GRBL, stops the stream, and invalidates all manual references.",
        )
        self._section(
            "Spindle behavior",
            "A file may contain M3/M4/M5 spindle commands. For an air cut, use a file that contains no spindle-start command and "
            "leave the spindle off. For a real engraving, start it manually below only when appropriate or let validated file "
            "commands control it.",
        )
        spindle = ttk.Frame(self.content)
        spindle.pack(fill="x", pady=8)
        ttk.Label(spindle, text="Spindle RPM").pack(side="left")
        ttk.Spinbox(spindle, from_=1, to=24000, textvariable=self.app.job_panel.rpm_var, width=9).pack(side="left", padx=8)
        ttk.Button(spindle, text="Start spindle…", command=self.app.start_spindle).pack(side="left", padx=3)
        ttk.Button(spindle, text="Stop spindle", command=self.app.stop_spindle).pack(side="left", padx=3)
        self._action("Start validated engraving job…", self._start_job)
        ttk.Label(self.content, textvariable=self.app.job_panel.progress_text_var, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=8
        )
        self.next_button.configure(text="Close wizard", command=self.close)

    def _start_job(self) -> None:
        self.app.start_job()
        self._update_gate()

    def _fit_status(self) -> tuple[bool, str]:
        program = self.app.job_panel.program
        if program is None:
            return False, "Load a G-code file first."
        return self.app._job_fit(program)

    def _ready(self) -> tuple[bool, str]:
        if self.index == 0:
            return self.understood_var.get(), "Acknowledge manual-operation responsibility to continue."
        if self.index == 1:
            ready = self.app.connection.connected and self.app.status is not None and self.app.status.can_jog
            return ready, "Connect and wait for GRBL to report Idle."
        if self.index == 2:
            try:
                shown = MachineProfile(
                    name=self.app.profile_name_var.get().strip(),
                    travel_x=float(self.app.travel_vars["X"].get()),
                    travel_y=float(self.app.travel_vars["Y"].get()),
                    travel_z=float(self.app.travel_vars["Z"].get()),
                    safe_z=float(self.app.safe_z_var.get()),
                )
                shown.validate()
                if shown != self.app.profile:
                    return False, "The displayed values are valid but have not been saved."
                return True, "The saved machine profile is valid."
            except (ValueError, tk.TclError) as exc:
                return False, f"Save valid measured travel values: {exc}"
        if self.index == 3:
            return self.app.envelope.trusted, "Establish the manual machine reference to continue."
        if self.index == 4:
            ready = self.app.work_zero_confirmed and self.app.work_offset is not None
            return ready, "Set XYZ work zero and wait for GRBL to report the updated offset."
        if self.index == 5:
            return self.app.job_panel.program is not None, "Load and validate a G-code file to continue."
        if self.index == 6:
            fits, reason = self._fit_status()
            return fits and self.preview_reviewed_var.get(), reason if not fits else "Confirm that you reviewed the preview."
        if self.index == 7:
            checked = self.material_secure_var.get() and self.tool_secure_var.get() and self.power_ready_var.get()
            return checked, "Complete all three physical preflight checks."
        ready = self.app.job.state in {"running", "paused", "complete"}
        return ready, "Start the validated job when the machine is ready, or close the wizard without starting."

    def _update_gate(self) -> None:
        ready, message = self._ready()
        self.status_var.set(("Ready — " if ready else "Waiting — ") + message)
        if self.index < len(self.STEP_TITLES) - 1:
            self.next_button.configure(state="normal" if ready else "disabled")
        else:
            self.next_button.configure(state="normal")

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        self._update_gate()
        self.after(300, self._refresh)

    def next(self) -> None:
        ready, message = self._ready()
        if not ready:
            messagebox.showwarning("Step incomplete", message, parent=self)
            return
        if self.index < len(self.STEP_TITLES) - 1:
            self.index += 1
            self.render()

    def back(self) -> None:
        if self.index:
            self.index -= 1
            self.render()

    def reset_job_confirmations(self) -> None:
        self.preview_reviewed_var.set(False)
        self.material_secure_var.set(False)
        self.tool_secure_var.set(False)
        self.power_ready_var.set(False)
        self._update_gate()

    def close(self) -> None:
        self.app.setup_wizard = None
        self.destroy()
