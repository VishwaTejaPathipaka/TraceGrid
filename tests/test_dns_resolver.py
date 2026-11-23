import socket
import subprocess
from threading import BoundedSemaphore
from time import monotonic
from unittest.mock import MagicMock, Mock

import pytest

from app.services import dns_resolver


def test_system_resolver_child_returns_numeric_sockaddrs():
    assert (socket.AF_INET, ("127.0.0.1", 443)) in dns_resolver.lookup_host(
        "127.0.0.1", 443, monotonic() + 5,
    )


def test_dns_timeout_kills_child_and_releases_slot(monkeypatch):
    process = MagicMock()
    process.__enter__.return_value = process
    process.communicate.side_effect = subprocess.TimeoutExpired("resolver", 1.0)
    monkeypatch.setattr(dns_resolver.subprocess, "Popen", Mock(return_value=process))
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(dns_resolver, "_RESOLVER_SLOTS", slots)

    with pytest.raises(TimeoutError, match="DNS lookup timed out"):
        dns_resolver.lookup_host("example.com", 443, monotonic() + 1)

    process.kill.assert_called_once()
    process.__exit__.assert_called_once()
    assert slots.acquire(blocking=False)
    slots.release()


def test_dns_capacity_wait_expires_without_starting_another_child(monkeypatch):
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(dns_resolver, "_RESOLVER_SLOTS", slots)
    start = Mock()
    monkeypatch.setattr(dns_resolver.subprocess, "Popen", start)

    with pytest.raises(TimeoutError):
        dns_resolver.lookup_host("example.com", 443, monotonic() + 0.05)

    start.assert_not_called()
    slots.release()


def test_reaps_a_stalled_resolver_process(monkeypatch, tmp_path):
    child = tmp_path / "wait_for_dns.py"
    child.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(dns_resolver, "_RESOLVER_SCRIPT", str(child))

    started = monotonic()
    with pytest.raises(TimeoutError, match="DNS lookup timed out"):
        dns_resolver.lookup_host("example.com", 443, started + 0.25)
    assert monotonic() - started < 3


def test_preserves_dns_error_code_from_child(monkeypatch):
    process = MagicMock()
    process.__enter__.return_value = process
    process.returncode = 0
    process.communicate.return_value = (f'{{"error": {socket.EAI_AGAIN}}}'.encode(), None)
    monkeypatch.setattr(dns_resolver.subprocess, "Popen", Mock(return_value=process))

    with pytest.raises(socket.gaierror) as error:
        dns_resolver.lookup_host("example.com", 443, monotonic() + 1)

    assert error.value.errno == socket.EAI_AGAIN
