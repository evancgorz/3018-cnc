"""Small dependency-free authenticated HTTP companion for Pine Live."""

from __future__ import annotations

import html
import json
import re
import secrets
import socket
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .commands import CommandLedger, RemoteCommand, RemoteCommandResult
from .frames import FrameHub
from .models import LiveStatusSnapshot
from .security import LiveSession, PairingManager


def is_private_bind_address(host: str) -> bool:
    """Permit loopback/private addresses, never wildcard or public interfaces."""
    if host.lower() in {"localhost", "ip6-localhost"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_unspecified and (address.is_loopback or address.is_private or address.is_link_local)


def private_bind_hosts() -> tuple[str, ...]:
    """Return usable local IPv4 addresses without ever proposing wildcard bind."""
    hosts: list[str] = ["127.0.0.1"]
    try:
        candidates = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        candidates = []
    for candidate in candidates:
        host = candidate[4][0]
        if host not in hosts and is_private_bind_address(host):
            hosts.append(host)
    return tuple(hosts)


class LiveWebServer:
    """Threaded HTTP adapter; all controller work is delegated to callables."""

    MAX_BODY = 4096
    MAX_VIEWERS = 3

    def __init__(
        self,
        snapshot: Callable[[], LiveStatusSnapshot],
        command_submit: Callable[[RemoteCommand], RemoteCommandResult],
        *,
        frame_hub: FrameHub | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        pairing: PairingManager | None = None,
        public_url: str = "",
        allowed_origins: tuple[str, ...] = (),
        secure_cookie: bool = False,
    ) -> None:
        if not is_private_bind_address(host):
            raise ValueError("Pine Live can bind only to a loopback or private interface")
        self.snapshot = snapshot
        self.frames = frame_hub or FrameHub()
        self.pairing = pairing or PairingManager()
        self.public_url = public_url.rstrip("/")
        self.allowed_origins = tuple(origin.rstrip("/") for origin in allowed_origins if origin)
        self.secure_cookie = secure_cookie
        self._ledger = CommandLedger(command_submit)
        self._server = ThreadingHTTPServer((host, port), self._handler_type())
        self._server.daemon_threads = True
        self._server.allow_reuse_address = True
        self._server.live_owner = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._viewer_lock = threading.Lock()
        self._viewers = 0
        self._rate_lock = threading.Lock()
        self._rate_events: dict[str, list[float]] = {}

    def _handler_type(self):
        owner = self

        class Handler(_LiveHandler):
            live_owner = owner

        return Handler

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[0], self._server.server_address[1]

    @property
    def url(self) -> str:
        if self.public_url:
            return self.public_url + "/"
        return f"http://{self.address[0]}:{self.address[1]}/"

    @property
    def viewer_count(self) -> int:
        with self._viewer_lock:
            return self._viewers

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stopping.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._server.serve_forever, name="pine-live-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.pairing.revoke_all()
        self.frames.close()
        self._server.shutdown()
        self._server.server_close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _acquire_viewer(self) -> bool:
        with self._viewer_lock:
            if self._viewers >= self.MAX_VIEWERS:
                return False
            self._viewers += 1
            return True

    def _release_viewer(self) -> None:
        with self._viewer_lock:
            self._viewers = max(0, self._viewers - 1)

    def rate_allowed(self, key: str, *, limit: int = 60, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            events = [stamp for stamp in self._rate_events.get(key, []) if now - stamp < window]
            if len(events) >= limit:
                self._rate_events[key] = events
                return False
            events.append(now)
            self._rate_events[key] = events
            return True

    def submit(self, command: RemoteCommand) -> RemoteCommandResult:
        return self._ledger.submit(command)


class _LiveHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PineLive/1"
    live_owner: LiveWebServer

    def log_message(self, _format, *args) -> None:
        return

    @property
    def owner(self) -> LiveWebServer:
        return self.live_owner

    def _headers(self, content_type: str, *, length: int | None = None, cache: bool = False) -> None:
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "public, max-age=300" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=() microphone=() geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'nonce-{_MOBILE_SCRIPT_NONCE}'; connect-src 'self'",
        )

    def _respond(self, code: int, payload: dict[str, object], *, cookie: str = "") -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self._headers("application/json; charset=utf-8", length=len(body))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str, *, cookie: str = "") -> None:
        content = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._headers("text/html; charset=utf-8", length=len(content))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request length")
        if length < 0 or length > self.owner.MAX_BODY:
            raise ValueError("Request is too large")
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            value = json.loads(raw.decode("utf-8") or "{}")
            return value if isinstance(value, dict) else {}
        return {key: values[-1] for key, values in parse_qs(raw.decode("utf-8")).items()}

    def _session(self) -> LiveSession | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("pine_live_session")
        if morsel is None:
            return None
        return self.owner.pairing.authenticate(morsel.value)

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        normalised = origin.rstrip("/")
        if normalised in self.owner.allowed_origins:
            return True
        host = parsed.hostname
        return parsed.scheme == "http" and host == self.server.server_address[0] and parsed.port in {None, self.server.server_address[1]}

    def _require_session(self, *, command: bool = False) -> LiveSession | None:
        if not self.owner.rate_allowed(f"{self.client_address[0]}:protected", limit=120):
            self._respond(HTTPStatus.TOO_MANY_REQUESTS, {"error": "rate_limit"})
            return None
        if not self._origin_ok():
            self._respond(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return None
        session = self._session()
        if session is None:
            self._respond(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
            return None
        if command and not self.headers.get("X-CSRF-Token"):
            self._respond(HTTPStatus.FORBIDDEN, {"error": "csrf_required"})
            return None
        if command and self.headers.get("X-CSRF-Token") != session.csrf_token:
            self._respond(HTTPStatus.FORBIDDEN, {"error": "csrf_invalid"})
            return None
        return session

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._html(_MOBILE_HTML.replace("<script>", f'<script nonce="{_MOBILE_SCRIPT_NONCE}">', 1))
            return
        if path == "/api/v1/status/events":
            if self._require_session() is None:
                return
            self._sse()
            return
        if path == "/api/v1/camera.mjpg":
            if self._require_session() is None:
                return
            self._mjpeg()
            return
        if path == "/health":
            self._respond(HTTPStatus.OK, {"ok": self.owner.running})
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/pair":
            self._pair()
            return
        if path == "/api/v1/session/logout":
            session = self._require_session(command=True)
            if session:
                self.owner.pairing.revoke(session.session_id)
                cookie = "pine_live_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"
                if self.owner.secure_cookie:
                    cookie += "; Secure"
                self._respond(HTTPStatus.OK, {"ok": True}, cookie=cookie)
            return
        match = re.fullmatch(r"/api/v1/jobs/([^/]+)/(pause|resume|abort|abort/confirm)", path)
        if match:
            self._command(match.group(1), match.group(2))
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _pair(self) -> None:
        if not self.owner.rate_allowed(f"{self.client_address[0]}:pair", limit=10):
            self._respond(HTTPStatus.TOO_MANY_REQUESTS, {"error": "rate_limit"})
            return
        if not self._origin_ok():
            self._respond(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return
        try:
            data = self._read_body()
            code = str(data.get("code", ""))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self._respond(HTTPStatus.BAD_REQUEST, {"error": "invalid_pairing_request"})
            return
        session = self.owner.pairing.pair(code)
        if session is None:
            self._respond(HTTPStatus.UNAUTHORIZED, {"error": "pairing_code_invalid_or_expired"})
            return
        cookie = f"pine_live_session={session.token}; Max-Age=43200; Path=/; HttpOnly; SameSite=Strict"
        if self.owner.secure_cookie:
            cookie += "; Secure"
        self._respond(HTTPStatus.OK, {"ok": True, "csrf_token": session.csrf_token}, cookie=cookie)

    def _command(self, job_nonce: str, action: str) -> None:
        session = self._require_session(command=True)
        if session is None:
            return
        try:
            data = self._read_body()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self._respond(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        requested_nonce = str(data.get("job_nonce", job_nonce))
        if requested_nonce != job_nonce:
            self._respond(HTTPStatus.CONFLICT, {"error": "job_nonce_mismatch"})
            return
        request_id = str(data.get("request_id", ""))[:80]
        if not request_id:
            self._respond(HTTPStatus.BAD_REQUEST, {"error": "request_id_required"})
            return
        if action == "abort/confirm":
            confirmation = self.owner.pairing.issue_abort_confirmation(session, job_nonce)
            self._respond(HTTPStatus.OK, {"ok": True, "confirmation": confirmation})
            return
        if action == "abort":
            confirmation = str(data.get("confirmation", ""))
            if not self.owner.pairing.consume_abort_confirmation(session, job_nonce, confirmation):
                self._respond(HTTPStatus.CONFLICT, {"error": "abort_confirmation_invalid_or_expired"})
                return
        command = RemoteCommand(request_id, session.session_id, action, job_nonce, __import__("time").monotonic(), str(data.get("confirmation", "")))
        result = self.owner.submit(command)
        self._respond(result.status_code, result.as_json())

    def _sse(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._headers("text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sequence = -1
        try:
            for _ in range(60):
                snapshot = self.owner.snapshot()
                if snapshot.sequence != sequence:
                    payload = json.dumps(snapshot.as_json(), separators=(",", ":"))
                    self.wfile.write(f"event: status\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    sequence = snapshot.sequence
                else:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                if self.owner._stopping.wait(1.0):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _mjpeg(self) -> None:
        if not self.owner._acquire_viewer():
            self._respond(HTTPStatus.TOO_MANY_REQUESTS, {"error": "viewer_limit_reached"})
            return
        try:
            self.send_response(HTTPStatus.OK)
            self._headers("multipart/x-mixed-replace; boundary=frame")
            self.send_header("Connection", "close")
            self.end_headers()
            generation = 0
            for _ in range(300):
                frame = self.owner.frames.wait_next(generation, 1.0)
                if frame is None:
                    if self.owner._stopping.is_set():
                        break
                    continue
                generation = frame.generation
                part = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame.jpeg)).encode("ascii") + b"\r\n\r\n" + frame.jpeg + b"\r\n"
                self.wfile.write(part)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.owner._release_viewer()


_MOBILE_SCRIPT_NONCE = secrets.token_urlsafe(24)


_MOBILE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pine Live</title>
<style>
:root{color-scheme:dark;--bg:#11151b;--panel:#1d232c;--line:#34404e;--text:#f3f6fa;--muted:#a8b3c0;--blue:#168bff;--red:#d94d5c}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#1a2736,var(--bg) 45%);font:16px system-ui,sans-serif;color:var(--text)}main{max-width:760px;margin:auto;padding:20px 16px 40px}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}h1{font-size:22px;margin:0;letter-spacing:.12em}h2{font-size:17px;margin:0 0 12px}.badge{border:1px solid var(--line);border-radius:99px;padding:7px 11px;color:var(--muted);font-size:13px}.card{background:color-mix(in srgb,var(--panel) 92%,transparent);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 10px 30px #0003}.video{aspect-ratio:16/9;background:#080b0f;border-radius:11px;overflow:hidden;display:grid;place-items:center;color:var(--muted)}.video img{width:100%;height:100%;object-fit:contain}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric{padding:10px;background:#151a21;border-radius:10px}.metric small{display:block;color:var(--muted);font-size:12px;margin-bottom:3px}.metric strong{font-size:14px}.progress{height:8px;background:#0d1116;border-radius:9px;overflow:hidden}.bar{height:100%;width:0;background:var(--blue);transition:width .2s}.controls{display:flex;gap:10px;margin-top:14px}button,input{font:inherit;min-height:46px;border-radius:10px;border:1px solid var(--line)}button{flex:1;background:#25303c;color:var(--text);cursor:pointer;font-weight:650}button.primary{background:var(--blue);border-color:var(--blue)}button.danger{background:var(--red);border-color:var(--red)}button:disabled{opacity:.45;cursor:not-allowed}.pair{display:grid;gap:10px}.pair input{padding:0 12px;background:#10151b;color:var(--text)}.error{color:#ffb0b7}.muted{color:var(--muted);font-size:13px}.hidden{display:none}@media(max-width:520px){main{padding:14px 10px}.grid{grid-template-columns:1fr}.controls{flex-direction:column}header{margin-bottom:10px}}
</style></head><body><main><header><h1>PINE LIVE</h1><span id="badge" class="badge">Pairing required</span></header>
<section id="pairCard" class="card pair"><h2>Pair this device</h2><p class="muted">Enter the one-time code shown in Pine Live on the Pine computer.</p><input id="code" inputmode="numeric" autocomplete="one-time-code" placeholder="0000-0000" maxlength="9"><button class="primary" id="pair">Pair device</button><p id="pairError" class="error"></p></section>
<section id="app" class="hidden"><section class="card"><div class="video"><img id="camera" alt="Live CNC camera feed"><span id="cameraText">Camera is off or unavailable</span></div></section>
<section class="card"><h2 id="job">No active job</h2><div class="progress"><div id="bar" class="bar"></div></div><p class="muted" id="jobMeta">Waiting for Pine status…</p><div class="grid"><div class="metric"><small>Machine</small><strong id="machine">—</strong></div><div class="metric"><small>Work</small><strong id="work">—</strong></div><div class="metric"><small>Controller</small><strong id="state">Unknown</strong></div><div class="metric"><small>Spindle / feed</small><strong id="spindle">Off / 0</strong></div></div><div class="controls"><button id="pause">Pause</button><button id="resume">Resume</button><button class="danger" id="abort">Abort</button></div><p id="message" class="muted"></p></section></section>
<script>
const $=id=>document.getElementById(id);let csrf='',snapshot=null,source=null,stale=true,pending=false;
const hashCode=decodeURIComponent(location.hash.slice(1));if(hashCode)$('code').value=hashCode;
function showApp(){ $('pairCard').classList.add('hidden');$('app').classList.remove('hidden');$('camera').src='/api/v1/camera.mjpg';startEvents(); }
function setMessage(t,err=false){$('message').textContent=t;$('message').className=err?'error':'muted'}
function update(s){snapshot=s;stale=(Date.now()-Date.parse(s.timestamp)>3000);$('badge').textContent=(s.connected?'Connected':'Disconnected')+' · '+(stale?'Stale':'Live');$('job').textContent=s.job_name||'No active job';$('jobMeta').textContent=s.job_state+' · '+s.progress+'% · '+(s.remaining_seconds==null?'—':Math.ceil(s.remaining_seconds/60)+' min remaining');$('bar').style.width=s.progress+'%';$('machine').textContent=s.machine_position;$('work').textContent=s.work_position;$('state').textContent=s.grbl_state;$('spindle').textContent=s.spindle+' / '+s.feed;$('pause').disabled=stale||pending||!s.can_pause;$('resume').disabled=stale||pending||!s.can_resume;$('abort').disabled=stale||pending||!s.can_abort}
function startEvents(){if(source)source.close();source=new EventSource('/api/v1/status/events');source.onmessage=e=>update(JSON.parse(e.data));source.addEventListener('status',e=>update(JSON.parse(e.data)));source.onerror=()=>{$('badge').textContent='Status unavailable';stale=true;update(snapshot||{timestamp:new Date(0).toISOString(),connected:false,job_state:'offline',progress:0,can_pause:false,can_resume:false,can_abort:false,machine_position:'—',work_position:'—',grbl_state:'Unknown',spindle:'Off',feed:'0'});setTimeout(startEvents,3000)}}
async function command(action){if(!snapshot||stale||pending)return; if(action==='abort'&&!window.confirmationShown){window.confirmationShown=true;setMessage('Press Abort again to confirm this job cannot be resumed.',true);return}pending=true;update(snapshot);let url='/api/v1/jobs/'+encodeURIComponent(snapshot.job_nonce)+'/'+action;let body={request_id:crypto.randomUUID(),job_nonce:snapshot.job_nonce};if(action==='abort'){body.confirmation=window.abortConfirmation||''}try{if(action==='abort'&&!window.abortConfirmation){let c=await fetch(url+'/confirm',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});let j=await c.json();if(!c.ok)throw Error(j.error);window.abortConfirmation=j.confirmation;setMessage('Press Abort again to confirm this job cannot be resumed.',true);return}let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});let j=await r.json();setMessage(j.message||j.error,r.status>=400);if(r.ok)window.confirmationShown=false}catch(e){setMessage(e.message,true)}finally{pending=false;if(snapshot)update(snapshot)}}
$('pair').onclick=async()=>{try{let r=await fetch('/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value})});let j=await r.json();if(!r.ok)throw Error(j.error);csrf=j.csrf_token;showApp()}catch(e){$('pairError').textContent=e.message}};$('pause').onclick=()=>command('pause');$('resume').onclick=()=>command('resume');$('abort').onclick=()=>command('abort');
</script></main></body></html>"""
