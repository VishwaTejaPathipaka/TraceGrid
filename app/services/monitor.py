import socket
import ssl
from selectors import DefaultSelector, EVENT_READ, EVENT_WRITE
from time import monotonic

import h11

from app.services.dns_resolver import is_missing_hostname, remaining_time
from app.services.monitoring_policy import (
    MonitoringPolicyError,
    parse_monitoring_url,
    resolve_public_addresses,
)


PROBE_TIMEOUT = 10.0
MAX_RESPONSE_HEADER_BYTES = 32768
_TLS_CONTEXT = ssl.create_default_context()


def _connect(addresses, deadline):
    last_error = None
    for family, sockaddr in addresses:
        remaining_time(deadline)
        try:
            sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        except OSError as error:
            last_error = error
            continue
        try:
            sock.settimeout(remaining_time(deadline))
            # The sockaddr was validated as numeric, so connect never resolves the hostname.
            sock.connect(sockaddr)
            return sock
        except OSError as error:
            last_error = error
            sock.close()

    remaining_time(deadline)
    raise last_error or OSError("Unable to connect to a monitoring destination")


def _socket_operation(sock, operation, selector, deadline, event):
    while True:
        remaining_time(deadline)
        try:
            return operation()
        except ssl.SSLWantReadError:
            readiness = EVENT_READ
        except ssl.SSLWantWriteError:
            readiness = EVENT_WRITE
        except BlockingIOError:
            readiness = event

        selector.register(sock, readiness)
        try:
            if not selector.select(remaining_time(deadline)):
                raise TimeoutError("Monitoring deadline exceeded")
        finally:
            selector.unregister(sock)


def _request_status(target, addresses, method, deadline):
    with _connect(addresses, deadline) as raw_socket, DefaultSelector() as selector:
        raw_socket.setblocking(False)
        if target.scheme == "https":
            remaining_time(deadline)
            hostname = target.raw_host.decode("ascii").rstrip(".")
            with _TLS_CONTEXT.wrap_socket(
                raw_socket, server_hostname=hostname, do_handshake_on_connect=False,
            ) as tls_socket:
                _socket_operation(tls_socket, tls_socket.do_handshake, selector, deadline, EVENT_READ)
                return _exchange_headers(tls_socket, target, method, selector, deadline)

        return _exchange_headers(raw_socket, target, method, selector, deadline)


def _exchange_headers(sock, target, method, selector, deadline):
    http = h11.Connection(h11.CLIENT)
    request = http.send(h11.Request(
        method=method, target=target.raw_path,
        headers=[(b"Host", target.netloc), (b"Connection", b"close")],
    )) + http.send(h11.EndOfMessage())

    while request:
        sent = _socket_operation(sock, lambda: sock.send(request), selector, deadline, EVENT_WRITE)
        if sent == 0:
            raise ConnectionError("Monitoring connection closed before sending the request")
        request = request[sent:]

    received = 0
    while True:
        remaining_time(deadline)
        event = http.next_event()
        if isinstance(event, h11.Response) or (
            isinstance(event, h11.InformationalResponse) and event.status_code == 101
        ):
            remaining_time(deadline)
            return event.status_code
        if event is h11.NEED_DATA:
            data = _socket_operation(sock, lambda: sock.recv(4096), selector, deadline, EVENT_READ)
            received += len(data)
            if received > MAX_RESPONSE_HEADER_BYTES:
                raise h11.RemoteProtocolError("Monitoring response headers exceeded the read budget")
            http.receive_data(data)
        elif not isinstance(event, h11.InformationalResponse):
            raise ConnectionError("Monitoring connection closed before receiving response headers")


def check_api(url: str, method: str = "GET"):
    started_at = monotonic()
    deadline = started_at + PROBE_TIMEOUT
    if method not in {"GET", "HEAD"}:
        raise MonitoringPolicyError("Change the monitoring method to GET or HEAD.")

    target = parse_monitoring_url(url)
    try:
        addresses = resolve_public_addresses(target, deadline)
        remaining_time(deadline)
    except socket.gaierror as error:
        return _result(started_at, "DOWN" if is_missing_hostname(error) else "ERROR", "dns_resolution")
    except TimeoutError:
        return _result(started_at, "ERROR", "dns_timeout")
    except MonitoringPolicyError:
        raise
    except (OSError, ValueError):
        return _result(started_at, "ERROR", "dns_resolver")

    try:
        status_code = _request_status(target, addresses, method, deadline)
    except ssl.SSLCertVerificationError:
        return _result(started_at, "DOWN", "tls_verification")
    except ssl.SSLError:
        return _result(started_at, "DOWN", "tls_error")
    except TimeoutError:
        return _result(started_at, "DOWN", "timeout")
    except ConnectionError:
        return _result(started_at, "DOWN", "connection")
    except h11.RemoteProtocolError:
        return _result(started_at, "DOWN", "http_protocol")
    except (OSError, h11.LocalProtocolError):
        return _result(started_at, "ERROR", "monitor_error")

    if 200 <= status_code < 300:
        return _result(started_at, "UP", status_code=status_code)
    if status_code in {300, 301, 302, 303, 307, 308}:
        return _result(started_at, "REDIRECT", "redirect", status_code)
    return _result(started_at, "DOWN", "http_error", status_code)


def _result(started_at, status, reason=None, status_code=None):
    return {
        "status": status,
        "status_code": status_code,
        "response_time": round((monotonic() - started_at) * 1000, 2),
        "reason": reason,
    }
