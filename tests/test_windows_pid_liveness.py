"""Process-owner liveness must never signal a Windows process."""
import ctypes
from ctypes import wintypes
import os
from unittest.mock import Mock

import pytest

from ttc3018_control.backend import discovery


def fake_api(monkeypatch, *, handle=101, exit_code=259, query_ok=True, error=0):
    api = Mock()
    api.OpenProcess.return_value = handle
    def get_exit_code(actual_handle, pointer):
        assert actual_handle == handle
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = exit_code
        return query_ok
    api.GetExitCodeProcess.side_effect = get_exit_code
    monkeypatch.setattr(discovery, "_windows_process_api", lambda: api)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    return api


def test_windows_current_owner_uses_query_only_handle_and_closes(monkeypatch):
    api = fake_api(monkeypatch)
    monkeypatch.setattr(discovery, "_IS_WINDOWS", True)
    def forbidden_kill(*_args):
        pytest.fail("Windows liveness must not invoke os.kill")
    monkeypatch.setattr(os, "kill", forbidden_kill)
    assert discovery.DiscoveryStore.pid_is_alive(os.getpid())
    api.OpenProcess.assert_called_once_with(0x1000, False, os.getpid())
    api.CloseHandle.assert_called_once_with(101)


@pytest.mark.parametrize("exit_code,alive", [(259, True), (0, False), (7, False)])
def test_windows_exit_status(monkeypatch, exit_code, alive):
    api = fake_api(monkeypatch, exit_code=exit_code)
    assert discovery._windows_pid_is_alive(10) is alive
    api.CloseHandle.assert_called_once_with(101)


@pytest.mark.parametrize("error,alive", [(87, False), (5, True), (0, True), (8, True)])
def test_windows_open_failure_preserves_unknown_owner(monkeypatch, error, alive):
    api = fake_api(monkeypatch, handle=None, error=error)
    assert discovery._windows_pid_is_alive(10) is alive
    api.GetExitCodeProcess.assert_not_called()
    api.CloseHandle.assert_not_called()


def test_windows_failed_query_is_alive_unknown_and_closes(monkeypatch):
    api = fake_api(monkeypatch, query_ok=False)
    assert discovery._windows_pid_is_alive(10)
    api.CloseHandle.assert_called_once_with(101)


@pytest.mark.parametrize("pid", [0, -1, 2**32, None, "bad"])
def test_invalid_windows_pid_does_not_call_api_or_signal(monkeypatch, pid):
    monkeypatch.setattr(discovery, "_IS_WINDOWS", True)
    api = Mock(side_effect=AssertionError("invalid PID must not touch an API"))
    monkeypatch.setattr(discovery, "_windows_process_api", api)
    monkeypatch.setattr(os, "kill", api)
    assert not discovery.DiscoveryStore.pid_is_alive(pid)
    api.assert_not_called()


def test_posix_keeps_signal_zero_semantics(monkeypatch):
    monkeypatch.setattr(discovery, "_IS_WINDOWS", False)
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    assert discovery.DiscoveryStore.pid_is_alive(123)
    kill.assert_called_once_with(123, 0)
    kill.side_effect = ProcessLookupError()
    assert not discovery.DiscoveryStore.pid_is_alive(123)
    kill.side_effect = PermissionError()
    assert discovery.DiscoveryStore.pid_is_alive(123)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows query-only API smoke check")
def test_native_windows_current_pid_and_absent_pid_without_signal(monkeypatch):
    monkeypatch.setattr(os, "kill", Mock(side_effect=AssertionError("signal forbidden")))
    assert discovery.DiscoveryStore.pid_is_alive(os.getpid())
    # DWORD max is not a valid Windows process ID; query only, no process action.
    assert not discovery.DiscoveryStore.pid_is_alive(0xFFFFFFFF)
