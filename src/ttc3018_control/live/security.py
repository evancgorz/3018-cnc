"""Pairing and session policy for the optional local Pine Live service."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import time


@dataclass(frozen=True)
class LiveSession:
    session_id: str
    token: str
    csrf_token: str
    last_seen: float


class PairingManager:
    PAIRING_TTL = 600.0
    SESSION_TTL = 12 * 60 * 60.0

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or time.monotonic
        self._pairing_code = self._new_code()
        self._pairing_expires = self._clock() + self.PAIRING_TTL
        self._sessions: dict[str, tuple[bytes, LiveSession]] = {}
        self._abort_confirmations: dict[tuple[str, str], tuple[str, float]] = {}

    @staticmethod
    def _new_code() -> str:
        return "-".join((str(secrets.randbelow(10000)).zfill(4), str(secrets.randbelow(10000)).zfill(4)))

    @property
    def pairing_code(self) -> str:
        if self._clock() >= self._pairing_expires:
            self.regenerate()
        return self._pairing_code

    @property
    def pairing_expires_at(self) -> float:
        return self._pairing_expires

    def regenerate(self) -> None:
        self._pairing_code = self._new_code()
        self._pairing_expires = self._clock() + self.PAIRING_TTL
        self.revoke_all()

    def pair(self, code: str) -> LiveSession | None:
        if not hmac.compare_digest(str(code).strip(), self.pairing_code):
            return None
        token = secrets.token_urlsafe(32)
        session = LiveSession(secrets.token_urlsafe(16), token, secrets.token_urlsafe(24), self._clock())
        self._sessions[session.session_id] = (self._digest(token), session)
        # Codes are one-time credentials. A fresh code is available only after
        # explicit regeneration, while the consumed code can never pair again.
        self._pairing_expires = self._clock() - 1
        return session

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    def authenticate(self, token: str) -> LiveSession | None:
        digest = self._digest(token)
        now = self._clock()
        for session_id, (stored, session) in tuple(self._sessions.items()):
            if now - session.last_seen > self.SESSION_TTL:
                self._sessions.pop(session_id, None)
                continue
            if hmac.compare_digest(stored, digest):
                refreshed = LiveSession(session.session_id, session.token, session.csrf_token, now)
                self._sessions[session_id] = (stored, refreshed)
                return refreshed
        return None

    def revoke_all(self) -> None:
        self._sessions.clear()
        self._abort_confirmations.clear()

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for key in tuple(self._abort_confirmations):
            if key[0] == session_id:
                self._abort_confirmations.pop(key, None)

    def issue_abort_confirmation(self, session: LiveSession, job_nonce: str) -> str:
        value = secrets.token_urlsafe(24)
        self._abort_confirmations[(session.session_id, job_nonce)] = (value, self._clock() + 60.0)
        return value

    def consume_abort_confirmation(self, session: LiveSession, job_nonce: str, value: str) -> bool:
        stored = self._abort_confirmations.pop((session.session_id, job_nonce), None)
        if stored is None or self._clock() >= stored[1]:
            return False
        return hmac.compare_digest(stored[0], value)

    @property
    def session_count(self) -> int:
        self._purge()
        return len(self._sessions)

    def _purge(self) -> None:
        now = self._clock()
        for session_id, (_, session) in tuple(self._sessions.items()):
            if now - session.last_seen > self.SESSION_TTL:
                self._sessions.pop(session_id, None)
