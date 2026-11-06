"""Opt-in, conservative replay of simple absolute metric milling programs."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid

from ..gcode import parse_gcode, validate_rapid_xy_clearance


def continuation(program, accepted: int, overlap: int = 32):
    """Return a self-contained suffix at a retract before the uncertain queue.

    Only the deliberately small G0/G1 exporter dialect is accepted. Accepted
    lines are not executed positions; rewind beyond planner/RX queue capacity.
    """
    commands = program.commands
    for command in commands:
        words = re.findall(r'([A-Z])([-+]?\d+(?:\.\d*)?)', command)
        if any(letter not in 'GMXYZFSP' for letter, _ in words):
            raise ValueError('Automatic continuation requires simple G0/G1 milling G-code')
        if any(letter == 'G' and float(value) not in (0, 1, 4, 17, 21, 90, 94, 54)
               or letter == 'M' and float(value) not in (2, 3, 5)
               for letter, value in words):
            raise ValueError('Automatic continuation cannot replay modal changes or side effects')
    if not any(all(word in command.split() for word in ('G21', 'G17', 'G90', 'G94', 'G54'))
               for command in commands[:8]):
        raise ValueError('Explicit metric absolute G54 preamble required')
    spindle = next((c for c in commands[:8] if re.fullmatch(r'M3 S\d+(?:\.\d+)?', c)), None)
    if spindle is None:
        raise ValueError('Explicit spindle setting required')
    if sum(bool(re.search(r'\bM3\b', c)) for c in commands) != 1 or any(
            'S' in c and c != spindle for c in commands):
        raise ValueError('Automatic continuation requires one unchanged spindle setting')
    if any(re.search(r'\bM(?:2|5)\b', c) for c in commands[:-2]):
        raise ValueError('Intermediate spindle stops or program ends are not replayable')
    limit = max(0, accepted - max(32, overlap))
    candidates = []
    for index in range(min(limit, len(commands) - 3)):
        if (re.fullmatch(r'G0 Z[0-9.]+', commands[index])
                and re.fullmatch(r'G0 X[-+0-9.]+ Y[-+0-9.]+', commands[index + 1])
                and re.fullmatch(r'G0 Z[0-9.]+', commands[index + 2])
                and re.fullmatch(r'G1 Z-[0-9.]+ F[0-9.]+', commands[index + 3])):
            candidates.append(index)
    if not candidates:
        raise ValueError('No verified retract boundary before bookmark')
    index = candidates[-1]
    safe_z = float(commands[index].split('Z')[1])
    text = '\n'.join(('G21 G17 G90 G94 G54', commands[index], spindle, 'G4 P2', *commands[index:])) + '\n'
    result = parse_gcode(text)
    validate_rapid_xy_clearance(result, safe_z)
    if commands[-2:] != ('M5', 'M2'):
        raise ValueError('Automatic continuation requires terminal M5/M2')
    return text, index, 4


class AutomaticContinuation:
    """One explicitly enabled job chain; never enables itself on startup."""
    MAX_ATTEMPTS = 3
    def __init__(self, root, clock=time.monotonic):
        self.root = Path(root)
        self.clock = clock
        self.path = self.root / 'config' / 'automatic-continuation.json'
        self.policy = None
        self.state = 'disabled'
        self.message = 'Automatic continuation disabled'
        self.before_return = None
        self.deadline = 0.0

    def snapshot(self):
        return {'state': self.state, 'message': self.message, 'enabled': self.policy is not None,
                'attempts': self.policy.get('attempts', 0) if self.policy else 0,
                'restart_requires_reenable': self.path.exists() and self.policy is None}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.policy or {}, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    @staticmethod
    def tool_context(app):
        definition = getattr(app, 'machine_definition', None)
        return json.dumps(asdict(definition) if is_dataclass(definition) else str(definition),
                          sort_keys=True, default=str)

    def disable(self, reason='Automatic continuation disabled by operator'):
        if self.policy is None:
            return
        self.policy = None
        self.state, self.message = 'disabled', reason
        self._save()

    def enable(self, app):
        program = app.program
        if program is None or not app.work_zero_confirmed or not app.reference_trusted:
            raise ValueError('Load a program and establish work zero before enabling automatic continuation')
        saved = getattr(app, '_saved_work_zero', None)
        if saved is None or set(saved.confirmed_axes) != set('XYZ'):
            raise ValueError('Confirmed saved XYZ work zero required')
        # Validate dialect and existence of restart entries without moving.
        continuation(program, len(program.commands))
        path = Path(program.path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != program.source_sha256:
            raise ValueError('Automatic continuation requires an unchanged saved source file')
        self.policy = {'machine_id': app.machine_id, 'current_sha256': program.source_sha256,
                       'original_sha256': program.source_sha256, 'original_path': str(path),
                       'source_offset': 0, 'preamble_commands': 0, 'attempts': 0,
                       'chain_id': uuid.uuid4().hex,
                       'tool_context': self.tool_context(app),
                       'saved_zero': [saved.x, saved.y, saved.z]}
        self.state, self.message = 'armed', 'Automatic continuation enabled for this job and saved work zero'
        self._save()

    def poll(self, runtime):
        if self.policy is None:
            return
        app = runtime.application
        p = self.policy
        state = str(getattr(app, 'job_state', ''))
        program = app.program
        if state in ('aborted', 'paused', 'complete'):
            self.disable(f'Automatic continuation canceled: job {state}')
            return
        saved = getattr(app, '_saved_work_zero', None)
        zero = [saved.x, saved.y, saved.z] if saved else None
        if (app.machine_id != p['machine_id'] or zero != p['saved_zero']
                or saved is None or set(saved.confirmed_axes) != set('XYZ')
                or self.tool_context(app) != p['tool_context']
                or program is None or program.source_sha256 != p['current_sha256']):
            self.disable('Automatic continuation canceled: machine, source or saved zero changed')
            return
        if runtime.safety_input_blocks_motion:
            self.disable('Automatic continuation canceled by independent safety input')
            return
        if self.state == 'returning':
            if self.clock() > self.deadline:
                self.disable('Work-zero return did not complete within 120 seconds')
                return
            status = app.status
            view = app.state
            work = view.work_position
            offset = app.work_offset
            if (status is None or status is self.before_return or not app.status_fresh or status.state != 'Idle'
                    or status.spindle != 0 or not app.reference_trusted or not app.work_zero_confirmed
                    or getattr(view, 'active_operation', '') or work is None or offset is None
                    or bool(getattr(app, 'motion_busy', False)) or int(getattr(app, 'manual_pending_acks', 0)) != 0
                    or any(abs(getattr(offset, axis) - p['saved_zero'][i]) > .001 for i, axis in enumerate('xyz'))
                    or any(abs(getattr(work, axis)) > .01 for axis in 'xyz')):
                return
            try:
                self._start(runtime)
            except (ValueError, RuntimeError, OSError) as exc:
                self.disable(f'Automatic continuation stopped: {exc}')
            return
        if state != 'failed' or self.state != 'armed':
            return
        error = str(getattr(app.job.streamer, 'error', ''))
        if not any(term in error.lower() for term in ('no responses', 'connection', 'controller reset')):
            self.disable('Automatic continuation canceled: failure was not a connection loss')
            return
        if runtime._job_watchdog_recovery.snapshot().get('state') != 'recovered':
            return
        if p['attempts'] >= self.MAX_ATTEMPTS:
            self.disable('Automatic continuation retry limit reached')
            return
        if not app.status_fresh or app.status is None or app.status.state != 'Idle' or app.status.spindle != 0 or not app.reference_trusted:
            return
        try:
            self.pending = continuation(program, int(app.job.streamer.acknowledged_count))
            self.before_return = app.status
            outcome = app.return_to_work_zero()
            if not outcome.accepted:
                raise ValueError(outcome.message)
            self.state, self.message = 'returning', 'Returning to saved work zero before automatic continuation'
            self.deadline = self.clock() + 120
        except (ValueError, RuntimeError, OSError) as exc:
            self.disable(f'Automatic continuation stopped: {exc}')

    def _start(self, runtime):
        app, p = runtime.application, self.policy
        if runtime.safety_input_blocks_motion:
            raise ValueError('Independent safety input blocks motion')
        text, index, preamble = self.pending
        source = Path(p['original_path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != p['original_sha256']:
            raise ValueError('Original source file changed')
        p['source_offset'] += max(0, index - p['preamble_commands'])
        p['preamble_commands'] = preamble
        p['attempts'] += 1
        output = self.root / 'artifacts' / 'automatic-continuations' / f"{p['chain_id']}-{p['attempts']}.nc"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='ascii', newline='\n') as stream:
            stream.write(text)
        app.load_program(output)
        p['current_sha256'] = app.program.source_sha256
        self._save()
        authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
        if not authorization.accepted:
            raise ValueError(authorization.message)
        outcome = app.start_authorized_job(authorization.token)
        if not outcome.accepted:
            raise ValueError(outcome.message)
        self.state, self.message = 'armed', 'Automatically continued from conservative overlap boundary'
