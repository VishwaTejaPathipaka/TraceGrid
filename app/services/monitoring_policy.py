import ipaddress
import socket
from time import monotonic
from urllib.parse import urlsplit

import httpx

from app.services.dns_resolver import lookup_host, remaining_time


class MonitoringPolicyError(ValueError):
    """The endpoint configuration cannot be used for monitoring."""


_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata",
    "metadata.goog",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
}
_BLOCKED_ADDRESSES = {ipaddress.ip_address("168.63.129.16")}
_BLOCKED_IPV4 = (
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
)
_IPV6_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")
_BLOCKED_IPV6 = (
    ipaddress.ip_network("2001::/23"),
    ipaddress.ip_network("2002::/16"),
    ipaddress.ip_network("3fff::/20"),
)
_DESTINATION_ERROR = "Monitoring requires a public destination. Use a public HTTP or HTTPS URL."


def _require_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id is not None:
            raise MonitoringPolicyError(_DESTINATION_ERROR)
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address not in _IPV6_GLOBAL_UNICAST or any(
            address in network for network in _BLOCKED_IPV6
        ):
            raise MonitoringPolicyError(_DESTINATION_ERROR)

    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address in _BLOCKED_ADDRESSES
        or any(address in network for network in _BLOCKED_IPV4)
    ):
        raise MonitoringPolicyError(_DESTINATION_ERROR)


def parse_monitoring_url(value: str) -> httpx.URL:
    try:
        parsed = urlsplit(value)
        url = httpx.URL(value)
    except (ValueError, httpx.InvalidURL) as error:
        raise MonitoringPolicyError("Enter a valid HTTP or HTTPS monitoring URL.") from error

    if url.scheme not in {"http", "https"} or not url.host:
        raise MonitoringPolicyError("Enter a valid HTTP or HTTPS monitoring URL.")
    if parsed.username is not None or url.userinfo:
        raise MonitoringPolicyError("Remove credentials from the monitoring URL.")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise MonitoringPolicyError("Enter a monitoring URL with a valid port.")

    host = url.raw_host.decode("ascii").lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost") or "%" in host:
        raise MonitoringPolicyError(_DESTINATION_ERROR)

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url

    _require_public_address(address)
    return url


def resolve_public_addresses(url: httpx.URL, deadline: float | None = None) -> list[tuple[int, tuple]]:
    if deadline is None:
        deadline = monotonic() + 5.0
    port = url.port or (443 if url.scheme == "https" else 80)
    host = url.raw_host.decode("ascii")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        answers = lookup_host(host, port, deadline)
    else:
        if literal.version == 4:
            answers = [(socket.AF_INET, (str(literal), port))]
        else:
            answers = [(socket.AF_INET6, (str(literal), port, 0, 0))]

    addresses = []
    for family, sockaddr in answers:
        remaining_time(deadline)
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise MonitoringPolicyError(_DESTINATION_ERROR)
        address = ipaddress.ip_address(sockaddr[0])
        if family == socket.AF_INET6 and sockaddr[3] != 0:
            raise MonitoringPolicyError(_DESTINATION_ERROR)
        _require_public_address(address)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            family = socket.AF_INET
            sockaddr = (str(address.ipv4_mapped), port)
        if (family, sockaddr) not in addresses:
            addresses.append((family, sockaddr))

    if not addresses:
        raise socket.gaierror(socket.EAI_NONAME, "Monitoring hostname returned no addresses.")
    return addresses
