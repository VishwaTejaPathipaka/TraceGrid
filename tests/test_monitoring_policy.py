import socket
import ssl
from time import monotonic
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, Mock

import pytest

from app.services import dns_resolver, monitor, monitoring_policy
from app.services.monitoring_policy import MonitoringPolicyError


@pytest.mark.parametrize("url", [
    "ftp://example.com/",
    "//example.com/",
    "http://",
    "https://example.com:0/",
    "https://example.com:65536/",
    "https://monitor:example@example.com/",
    "https://@example.com/",
    "http://api.localhost./",
    "http://metadata.google.internal./",
    "http://168.63.129.16/",
    "http://0.0.0.0/",
    "http://10.0.0.1/",
    "http://127.0.0.1/",
    "http://100.100.100.200/",
    "http://169.254.169.254/",
    "http://192.0.2.1/",
    "http://224.0.0.1/",
    "http://240.0.0.1/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[fe80::1]/",
    "http://[fd00:ec2::254]/",
    "http://[ff02::1]/",
    "http://[2001:db8::1]/",
    "http://[64:ff9b::a00:1]/",
    "http://[2002:a00:1::1]/",
])
def test_rejects_unsafe_urls_before_dns(monkeypatch, url):
    lookup = Mock()
    monkeypatch.setattr(monitoring_policy, "lookup_host", lookup)

    with pytest.raises(MonitoringPolicyError):
        monitor.check_api(url)

    lookup.assert_not_called()


def dns_answer(ip, port=443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return family, sockaddr


@pytest.mark.parametrize("blocked_ip", ["10.1.2.3", "::ffff:127.0.0.1", "fd00::1"])
def test_rejects_mixed_public_and_nonpublic_dns_answers(monkeypatch, blocked_ip):
    monkeypatch.setattr(monitoring_policy, "lookup_host", Mock(return_value=[
        dns_answer("8.8.8.8"), dns_answer(blocked_ip),
    ]))
    connect = Mock()
    monkeypatch.setattr(monitor, "_connect", connect)

    with pytest.raises(MonitoringPolicyError, match="public destination"):
        monitor.check_api("https://api.example.com/")

    connect.assert_not_called()


@pytest.mark.parametrize("failure, status, reason", [
    (socket.gaierror(socket.EAI_NONAME, "no name"), "DOWN", "dns_resolution"),
    (socket.gaierror(socket.EAI_AGAIN, "temporary failure"), "ERROR", "dns_resolution"),
    (TimeoutError(), "ERROR", "dns_timeout"),
    (OSError(), "ERROR", "dns_resolver"),
])
def test_dns_outcomes(monkeypatch, failure, status, reason):
    monkeypatch.setattr(monitoring_policy, "lookup_host", Mock(side_effect=failure))
    result = monitor.check_api("https://api.example.com/")
    assert result["status"] == status
    assert result["status_code"] is None
    assert result["reason"] == reason


@pytest.mark.parametrize("failure, status, reason", [
    (ConnectionRefusedError(), "DOWN", "connection"),
    (OSError(), "ERROR", "monitor_error"),
    (ssl.SSLError(), "DOWN", "tls_error"),
])
def test_transport_failure_outcomes(monkeypatch, failure, status, reason):
    monkeypatch.setattr(monitor, "_request_status", Mock(side_effect=failure))
    result = monitor.check_api("https://8.8.8.8/")
    assert (result["status"], result["reason"]) == (status, reason)


@pytest.mark.parametrize("code", [304, 404, 503])
def test_non_redirect_http_errors_keep_status_code(monkeypatch, code):
    monkeypatch.setattr(monitor, "_request_status", Mock(return_value=code))
    result = monitor.check_api("https://8.8.8.8/")
    assert (result["status"], result["status_code"], result["reason"]) == ("DOWN", code, "http_error")


def test_normalizes_public_ipv4_mapped_answers(monkeypatch):
    monkeypatch.setattr(monitoring_policy, "lookup_host", Mock(return_value=[
        dns_answer("::ffff:8.8.8.8"), dns_answer("8.8.8.8"),
    ]))
    target = monitoring_policy.parse_monitoring_url("https://api.example.com/")

    assert monitoring_policy.resolve_public_addresses(target) == [(socket.AF_INET, ("8.8.8.8", 443))]


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "TRACE"])
def test_rejects_legacy_methods_before_dns(monkeypatch, method):
    lookup = Mock()
    monkeypatch.setattr(monitoring_policy, "lookup_host", lookup)

    with pytest.raises(MonitoringPolicyError, match="GET or HEAD"):
        monitor.check_api("https://api.example.com/", method)

    lookup.assert_not_called()


def mock_socket(response=None):
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.send.side_effect = len
    sock.recv.return_value = response
    return sock


def test_pins_connection_and_preserves_http_and_tls_hostname(monkeypatch):
    address = "2606:4700:4700::1111"
    lookup = Mock(side_effect=[[dns_answer(address, 8443)], [dns_answer("127.0.0.1", 8443)]])
    monkeypatch.setattr(monitoring_policy, "lookup_host", lookup)
    # Fail if the transport tries to resolve the hostname again.
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=AssertionError("unexpected DNS lookup")))
    sock = mock_socket()
    socket_factory = Mock(return_value=sock)
    monkeypatch.setattr(socket, "socket", socket_factory)
    tls = monitor._TLS_CONTEXT
    assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
    tls_socket = mock_socket(b"HTTP/1.1 204 No Content\r\n\r\n")
    wrap = Mock(return_value=tls_socket)
    monkeypatch.setattr(tls, "wrap_socket", wrap)

    result = monitor.check_api("https://api.example.com:8443/status?full=true", "HEAD")

    assert result["status_code"] == 204
    assert result["status"] == "UP"
    lookup.assert_called_once_with("api.example.com", 8443, ANY)
    socket_factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    sock.connect.assert_called_once_with((address, 8443, 0, 0))
    wrap.assert_called_once_with(sock, server_hostname="api.example.com", do_handshake_on_connect=False)
    tls_socket.do_handshake.assert_called_once()
    request = tls_socket.send.call_args.args[0]
    assert request.startswith(b"HEAD /status?full=true HTTP/1.1\r\n")
    assert b"\r\nHost: api.example.com:8443\r\n" in request


def test_certificate_failure_closes_connection_before_sending_http(monkeypatch):
    monkeypatch.setattr(monitoring_policy, "lookup_host", Mock(return_value=[dns_answer("8.8.8.8")]))
    sock = mock_socket()
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    tls_socket = mock_socket()
    tls_socket.do_handshake.side_effect = ssl.SSLCertVerificationError("certificate mismatch")
    monkeypatch.setattr(monitor._TLS_CONTEXT, "wrap_socket", Mock(return_value=tls_socket))

    result = monitor.check_api("https://api.example.com/")

    assert result["status"] == "DOWN"
    assert result["status_code"] is None
    assert result["reason"] == "tls_verification"
    tls_socket.send.assert_not_called()
    tls_socket.__exit__.assert_called_once()
    sock.__exit__.assert_called_once()


@pytest.mark.parametrize("location", [b"http://redirect.example.com/", b"http://169.254.169.254/"])
def test_ignores_proxy_environment_and_returns_redirect_without_following(monkeypatch, location):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:8888")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.com:8888")
    monkeypatch.setenv("NO_PROXY", "")
    lookup = Mock(return_value=[dns_answer("8.8.8.8", 80)])
    monkeypatch.setattr(monitoring_policy, "lookup_host", lookup)
    sock = mock_socket(
        b"HTTP/1.1 302 Found\r\nLocation: " + location + b"\r\nContent-Length: 0\r\n\r\n"
    )
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))

    result = monitor.check_api("http://api.example.com/health")

    assert result["status_code"] == 302
    assert result["status"] == "REDIRECT"
    assert result["reason"] == "redirect"
    lookup.assert_called_once_with("api.example.com", 80, ANY)
    sock.connect.assert_called_once_with(("8.8.8.8", 80))
    sock.send.assert_called_once()
    assert sock.send.call_args.args[0].startswith(b"GET /health HTTP/1.1\r\n")


def test_dns_tcp_tls_and_headers_share_one_deadline(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(monitor, "monotonic", lambda: clock.now)
    monkeypatch.setattr(dns_resolver, "monotonic", lambda: clock.now)

    def lookup(host, port, deadline):
        assert deadline == 110.0
        clock.now += 3.0
        return [dns_answer("8.8.8.8")]

    def connect(address):
        clock.now += 3.0

    def handshake():
        clock.now += 3.0

    def receive(_):
        clock.now += 0.25
        return b"HTTP/1.1 100 Continue\r\n\r\n"

    raw_socket = mock_socket()
    raw_socket.connect.side_effect = connect
    tls_socket = mock_socket()
    tls_socket.do_handshake.side_effect = handshake
    tls_socket.recv.side_effect = receive
    monkeypatch.setattr(monitoring_policy, "lookup_host", lookup)
    monkeypatch.setattr(socket, "socket", Mock(return_value=raw_socket))
    monkeypatch.setattr(monitor._TLS_CONTEXT, "wrap_socket", Mock(return_value=tls_socket))

    result = monitor.check_api("https://api.example.com/")

    assert result == {"status": "DOWN", "status_code": None, "response_time": 10_000.0, "reason": "timeout"}
    raw_socket.settimeout.assert_called_once_with(7.0)
    assert tls_socket.recv.call_count == 4
    tls_socket.__exit__.assert_called_once()


def test_stalled_tls_handshake_waits_only_for_remaining_time(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(monitor, "monotonic", lambda: clock.now)
    monkeypatch.setattr(dns_resolver, "monotonic", lambda: clock.now)
    raw_socket = mock_socket()
    tls_socket = mock_socket()

    def handshake():
        clock.now += 8.0
        raise ssl.SSLWantReadError()

    tls_socket.do_handshake.side_effect = handshake
    selector = MagicMock()
    selector.__enter__.return_value = selector
    selector.select.return_value = []
    monkeypatch.setattr(monitor, "DefaultSelector", Mock(return_value=selector))
    monkeypatch.setattr(socket, "socket", Mock(return_value=raw_socket))
    monkeypatch.setattr(monitor._TLS_CONTEXT, "wrap_socket", Mock(return_value=tls_socket))

    result = monitor.check_api("https://8.8.8.8/")

    assert result["status"] == "DOWN"
    selector.register.assert_called_once_with(tls_socket, monitor.EVENT_READ)
    selector.select.assert_called_once_with(2.0)
    selector.unregister.assert_called_once_with(tls_socket)
    tls_socket.send.assert_not_called()


def test_tcp_fallback_uses_remaining_budget(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(monitor, "monotonic", lambda: clock.now)
    monkeypatch.setattr(dns_resolver, "monotonic", lambda: clock.now)
    first = mock_socket()
    second = mock_socket(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    def failed_connect(address):
        clock.now += 6.0
        raise ConnectionRefusedError()

    first.connect.side_effect = failed_connect
    monkeypatch.setattr(monitoring_policy, "lookup_host", Mock(return_value=[
        dns_answer("8.8.8.8", 80), dns_answer("2606:4700:4700::1111", 80),
    ]))
    monkeypatch.setattr(socket, "socket", Mock(side_effect=[first, second]))

    result = monitor.check_api("http://api.example.com/")

    assert result["status"] == "UP"
    first.close.assert_called_once()
    second.settimeout.assert_called_once_with(4.0)
    second.connect.assert_called_once_with(("2606:4700:4700::1111", 80, 0, 0))


def test_incomplete_headers_time_out_on_real_socket(monkeypatch):
    client_socket, server_socket = socket.socketpair()
    monkeypatch.setattr(monitor, "_connect", Mock(return_value=client_socket))
    monkeypatch.setattr(monitor, "PROBE_TIMEOUT", 0.25)

    with client_socket, server_socket:
        server_socket.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: ")
        started = monotonic()
        result = monitor.check_api("http://8.8.8.8/")

    assert result["status"] == "DOWN"
    assert result["status_code"] is None
    assert monotonic() - started < 3
    assert client_socket.fileno() == -1
