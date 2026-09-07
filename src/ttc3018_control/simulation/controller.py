"""Virtual GRBL controller speaking the same line protocol as DLC32."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable

from .plant import VirtualMachinePlant
from .models import SimulationFault
from .protocol import ParsedLine, ProtocolError, parse_line


@dataclass
class _Modal:
    absolute: bool = True
    units: str = "G21"
    motion: int = 0
    plane: str = "G17"
    feed_mode: str = "G94"
    wcs: int = 54
    tlo: float = 0.0
    feed: float = 300.0


class VirtualGrblController:
    """Byte-oriented controller core; output is drained asynchronously by a server."""

    def __init__(self, plant: VirtualMachinePlant | None = None, *, output: Callable[[str], None] | None = None) -> None:
        self.plant = plant or VirtualMachinePlant()
        self.output = output or (lambda _line: None)
        self._line_buffer = bytearray()
        self._deferred_lines: list[tuple[int, str]] = []
        self._responses: list[str] = []
        self._modal = _Modal()
        self.settings = {5: 0.0, 6: 0.0, 20: 0.0, 21: 25.0, 22: 0.0, 23: 3.0, 24: 25.0, 25: 500.0, 26: 250.0, 27: 1.0,
                         130: self.plant.profile.travel_x, 131: self.plant.profile.travel_y,
                         132: self.plant.profile.travel_z}
        self.alarm = False
        self.startup = True
        self._last_probe: tuple[float, float, float] | None = None
        self._line_sequence = 0
        self.faults: list[SimulationFault] = []
        self._delayed_ack_until: list[int] = []
        self.plant.on_limit = self._limit_alarm
        self.plant.on_block_complete = self._block_complete

    def boot(self) -> list[str]:
        lines = ["Grbl 1.1h ['$' for help]", "[MSG:Digital twin — no physical machine]"]
        self.startup = False
        self.alarm = False
        return lines

    def receive(self, data: bytes) -> None:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("GRBL input must be bytes")
        for byte in data:
            if byte in (ord("?"), ord("!"), ord("~"), 0x18, 0x85):
                self._realtime(byte)
            else:
                if len(self._line_buffer) >= self.plant.profile.rx_capacity:
                    self._line_buffer.clear()
                    self._emit("error:11")
                    continue
                self._line_buffer.append(byte)
                if byte in (10, 13):
                    line = bytes(self._line_buffer).decode("ascii", errors="replace").strip()
                    self._line_buffer.clear()
                    if line:
                        self._normal(line)

    def drain(self) -> tuple[str, ...]:
        values = tuple(self._responses)
        self._responses.clear()
        return values

    def advance(self, delta_ns: int) -> None:
        self.plant.advance(delta_ns)
        self._drain_deferred_lines()
        if self._delayed_ack_until:
            now = self.plant.clock.time_ns
            ready = [due for due in self._delayed_ack_until if due <= now]
            self._delayed_ack_until = [due for due in self._delayed_ack_until if due > now]
            for _due in ready:
                self._emit("ok")

    def install_fault(self, fault: SimulationFault) -> None:
        if not isinstance(fault, SimulationFault):
            raise TypeError("Expected SimulationFault")
        self.faults.append(fault)

    def clear_faults(self) -> None:
        self.faults.clear()

    def status_line(self) -> str:
        if self._fault_active("malformed_status"):
            return "<Malformed digital-twin status"
        snapshot = self.plant.snapshot()
        state = snapshot.state
        mpos = ",".join(f"{value:.3f}" for value in snapshot.machine_position)
        work_position = list(snapshot.work_position)
        # Tool length offset participates in the reported work coordinate;
        # machine position and persisted WCO remain independently observable.
        work_position[2] -= self._modal.tlo
        wpos = ",".join(f"{value:.3f}" for value in work_position)
        wco = ",".join(f"{value:.3f}" for value in snapshot.work_offset)
        planner_used = len(self.plant.queue) + (1 if self.plant.active is not None else 0)
        planner_free = max(0, self.plant.profile.planner_capacity - planner_used)
        rx_free = max(0, self.plant.profile.rx_capacity - len(self._line_buffer))
        pins = f"|Pn:{snapshot.pins}" if snapshot.pins else ""
        return f"<{state}|MPos:{mpos}|WPos:{wpos}|WCO:{wco}|Bf:{planner_free},{rx_free}|FS:{snapshot.feed:.0f},{snapshot.spindle_rpm:.0f}{pins}>"

    def _emit(self, line: str) -> None:
        self._responses.append(line)
        self.output(line)

    def _realtime(self, byte: int) -> None:
        if byte == ord("?"):
            self._emit(self.status_line())
        elif byte == ord("!"):
            self.plant.request_hold()
        elif byte == ord("~"):
            self.plant.resume()
        elif byte == 0x85:
            self.plant.cancel_jog()
        elif byte == 0x18:
            self._line_buffer.clear()
            self._deferred_lines.clear()
            self._delayed_ack_until.clear()
            self.plant.reset()
            self.alarm = False
            self._modal = _Modal()
            self._emit("Grbl 1.1h ['$' for help]")

    def _normal(self, line: str) -> None:
        self._line_sequence += 1
        sequence = self._line_sequence
        # GRBL accepts only explicit unlock/homing paths while alarmed;
        # ordinary motion must not be queued behind an uncleared alarm.
        alarm_command = line
        if line.startswith("$"):
            try:
                alarm_command = parse_line(line).raw
            except ProtocolError:
                alarm_command = ""
        if self.alarm and alarm_command not in {"$X", "$H"}:
            self._emit("ALARM:1")
            return
        if self._deferred_lines or self._planner_full_for(line):
            self._deferred_lines.append((sequence, line))
            return
        self._execute_normal(line, sequence)

    def _execute_normal(self, line: str, sequence: int) -> None:
        if self._fault_active("error", sequence) or self._fault_active("error_ack", sequence):
            self._emit("error:2")
            return
        suppress_ack = self._fault_active("missing_ack", sequence)
        delayed_ack = self._fault_active("delayed_ack", sequence)
        duplicate_ack = self._fault_active("duplicate_ack", sequence)
        try:
            if line.startswith("$"):
                # System commands share the parser's comment/case handling
                # with motion commands before dedicated dispatch.
                line = parse_line(line).raw
                self._system(line)
            elif line.startswith("[ESP"):
                self._emit("ok")
            else:
                parsed = parse_line(line)
                self._execute(parsed)
        except (ProtocolError, ValueError, RuntimeError) as exc:
            self._emit(f"error:1 ({exc})")
            return
        if not suppress_ack and not delayed_ack:
            self._emit("ok")
            if duplicate_ack:
                self._emit("ok")
        elif delayed_ack:
            delay_ms = 100.0
            for fault in self.faults:
                if fault.enabled and fault.name == "delayed_ack" and fault.value:
                    try: delay_ms = max(0.0, float(fault.value))
                    except ValueError: pass
                    break
            self._delayed_ack_until.append(self.plant.clock.time_ns + round(delay_ms * 1_000_000))

    def _drain_deferred_lines(self) -> None:
        while self._deferred_lines and not self._planner_full_for(self._deferred_lines[0][1]):
            sequence, line = self._deferred_lines.pop(0)
            self._execute_normal(line, sequence)

    def _planner_used(self) -> int:
        return len(self.plant.queue) + (1 if self.plant.active is not None else 0)

    def _planner_full_for(self, line: str) -> bool:
        if not self._line_uses_planner(line):
            return False
        return self._planner_used() >= self.plant.profile.planner_capacity

    @staticmethod
    def _line_uses_planner(line: str) -> bool:
        if line.startswith("$J="):
            return True
        if line.startswith("$") or line.startswith("[ESP"):
            return False
        try:
            parsed = parse_line(line)
        except (ProtocolError, ValueError):
            return False
        codes = {int(round(value)) for value in parsed.values("G")}
        return bool(codes.intersection({0, 1, 2, 3, 38}) or any(parsed.values(axis) for axis in "XYZ"))

    def _fault_active(self, name: str, sequence: int | None = None) -> bool:
        target_sequence = self._line_sequence if sequence is None else sequence
        return any(fault.enabled and fault.name == name and
                   (fault.at_sequence is None or fault.at_sequence == target_sequence)
                   for fault in self.faults)

    def _system(self, line: str) -> None:
        if line.startswith("$J="):
            # Jog is a GRBL system command, but its motion words follow the
            # ordinary parser grammar. It is always incremental and never a
            # probing operation.
            jog = parse_line(line[3:])
            previous_absolute = self._modal.absolute
            previous_motion = self._modal.motion
            self._modal.absolute = False
            self._modal.motion = 1
            try:
                if jog.values("F"):
                    self._modal.feed = jog.values("F")[-1]
                self._move(jog)
            finally:
                self._modal.absolute = previous_absolute
                self._modal.motion = previous_motion
            return
        if line == "$$":
            for number, value in sorted(self.settings.items()):
                self._emit(f"${number}={value:g}")
            return
        if line == "$I":
            self._emit("[VER:1.1h.digital-twin]")
            self._emit("[OPT:V,15,128]")
            return
        if line == "$G":
            self._emit(f"[GC:{self._modal.units} G{self._modal.motion} {self._modal.plane} {self._modal.feed_mode} G{self._modal.wcs}]")
            return
        if line == "$#":
            self._emit(f"[G54:{','.join(f'{v:.3f}' for v in self.plant.work_offset)}]")
            return
        if line == "$X":
            self.alarm = False
            self.plant.state = "Idle"
            return
        if line == "$H":
            self.plant.position[:] = [0.0, 0.0, 0.0]
            self.plant.state = "Idle"
            self.alarm = False
            return
        match = re.fullmatch(r"\$(\d+)\s*=\s*(-?(?:\d+(?:\.\d*)?|\.\d+))", line)
        if match is None:
            raise ProtocolError("unsupported system command")
        number, value = int(match.group(1)), float(match.group(2))
        if number not in self.settings or value < 0 or not math.isfinite(value):
            raise ProtocolError("unsupported or invalid setting")
        self.settings[number] = value

    def _execute(self, parsed: ParsedLine) -> None:
        g_codes = [int(round(value)) for value in parsed.values("G")]
        for code in g_codes:
            if code == 20:
                raise ProtocolError("inch mode is not supported")
            if code == 21:
                self._modal.units = "G21"
            elif code == 90:
                self._modal.absolute = True
            elif code == 91:
                self._modal.absolute = False
            elif code in (0, 1, 2, 3):
                self._modal.motion = code
            elif code == 17:
                self._modal.plane = "G17"
            elif code == 94:
                self._modal.feed_mode = "G94"
            elif code == 54:
                self._modal.wcs = 54
            elif code == 49:
                self._modal.tlo = 0.0
                self._emit("[TLO:0.000]")
            elif code == 43:
                self._modal.tlo = parsed.values("Z")[-1] if parsed.values("Z") else self._modal.tlo
                self._emit(f"[TLO:{self._modal.tlo:.3f}]")
            elif code == 10:
                self._set_offset(parsed)
            elif code == 38:
                self._probe(parsed)
            elif code == 4:
                # Dwell is represented by accepted command; deterministic tests
                # may advance the clock explicitly between responses.
                continue
            elif code in (40, 80):
                continue
            else:
                raise ProtocolError(f"unsupported G-code G{code}")
        if parsed.values("F"):
            self._modal.feed = parsed.values("F")[-1]
            if self._modal.feed <= 0:
                raise ProtocolError("feed must be positive")
        if parsed.values("S"):
            self.plant.set_spindle(parsed.values("S")[-1])
        for code in [int(round(value)) for value in parsed.values("M")]:
            if code in (3, 4):
                if not parsed.values("S"):
                    self.plant.set_spindle(max(self.plant.spindle_target, 1000.0))
            elif code in (5, 30, 2):
                self.plant.set_spindle(0.0)
            elif code in (0, 1):
                self.plant.request_hold()
            elif code not in (0, 1, 2, 3, 4, 5, 30):
                raise ProtocolError(f"unsupported M-code M{code}")
        if any(parsed.values(axis) for axis in "XYZ") and not any(code in (10, 38) for code in g_codes):
            self._move(parsed)

    def _move(self, parsed: ParsedLine, *, probing: bool = False) -> None:
        current = self.plant.machine_position
        # GRBL plans commands against the end of the already queued motion,
        # not the instantaneous pose.  This matters for the safe-move planner,
        # which intentionally emits a retract followed immediately by a move
        # back toward the workpiece.  Using the instantaneous pose for an
        # incremental command would turn ``Z30`` + ``Z-20`` into ``Z30`` +
        # ``Z-20`` from the original origin and spuriously hit a travel limit.
        planner_position = (
            self.plant.queue[-1].target
            if self.plant.queue
            else self.plant.active.target
            if self.plant.active is not None
            else current
        )
        target = list(current)
        for index, axis in enumerate("XYZ"):
            values = parsed.values(axis)
            if values:
                value = values[-1]
                if self._modal.absolute:
                    # GRBL absolute coordinates are work coordinates; convert
                    # them to the plant's machine frame using the active WCO.
                    target[index] = value + self.plant.work_offset[index]
                else:
                    target[index] = value + planner_position[index]
        feed = self._modal.feed if self._modal.motion != 0 else max(self._modal.feed, 3000.0)
        points: tuple[tuple[float, float, float], ...] = ()
        if self._modal.motion in (2, 3):
            points = self._arc_points(planner_position, tuple(target), parsed, clockwise=self._modal.motion == 2)
        self.plant.enqueue(tuple(target), feed=feed, rapid=self._modal.motion == 0, probing=probing, points=points)

    def _arc_points(self, start, end, parsed: ParsedLine, *, clockwise: bool):
        i = parsed.values("I")[-1] if parsed.values("I") else 0.0
        j = parsed.values("J")[-1] if parsed.values("J") else 0.0
        cx, cy = start[0] + i, start[1] + j
        radius = math.hypot(start[0] - cx, start[1] - cy)
        if radius <= 0:
            raise ProtocolError("arc radius is zero")
        start_angle, end_angle = math.atan2(start[1] - cy, start[0] - cx), math.atan2(end[1] - cy, end[0] - cx)
        sweep = end_angle - start_angle
        if clockwise and sweep >= 0:
            sweep -= math.tau
        if not clockwise and sweep <= 0:
            sweep += math.tau
        count = max(8, math.ceil(abs(sweep) / math.radians(5)))
        return tuple(tuple((cx + radius * math.cos(start_angle + sweep * n / count),
                            cy + radius * math.sin(start_angle + sweep * n / count),
                            start[2] + (end[2] - start[2]) * n / count)) for n in range(1, count + 1))

    def _set_offset(self, parsed: ParsedLine) -> None:
        if 20 not in [int(round(value)) for value in parsed.values("L")]:
            raise ProtocolError("only G10 L20 is supported")
        # G10 L20 receives the desired work-coordinate values at the current
        # machine pose.  GRBL stores WCO as MPos - WPos, rather than copying
        # the command words into WCO.  This is especially important for the
        # normal ``G10 ... X0 Y0 Z0`` work-zero command after jogging.
        machine_position = self.plant.machine_position
        values = list(self.plant.work_offset)
        axes = ""
        for index, axis in enumerate("XYZ"):
            if parsed.values(axis):
                requested_work = parsed.values(axis)[-1]
                values[index] = machine_position[index] - requested_work
                axes += axis
        self.plant.set_work_offset(tuple(values), axes)

    def _probe(self, parsed: ParsedLine) -> None:
        self._move(parsed, probing=True)
        # Report is emitted on block completion by the plant callback.

    def _block_complete(self, block) -> None:
        if block.probing:
            self._last_probe = self.plant.machine_position
            success = self.plant.probe_active
            self._emit(f"[PRB:{','.join(f'{v:.3f}' for v in self._last_probe)}:{1 if success else 0}]")
            self.plant.probe_active = False

    def _limit_alarm(self, position) -> None:
        self.alarm = True
        self._emit("ALARM:1")
