from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import IPv4Address, IPv4Network
import socket


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        address = info[4][0]
        parsed = IPv4Address(address)
        if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
            addresses.add(address)

    # The UDP socket is not connected over the network; connect() asks the OS
    # which local interface would route normal LAN traffic.
    try:
        endpoint = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        endpoint.connect(("192.0.2.1", 9))
        address = endpoint.getsockname()[0]
        endpoint.close()
        parsed = IPv4Address(address)
        if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
            addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def subnet_candidates(local_addresses: list[str]) -> list[str]:
    candidates: set[str] = set()
    local = set(local_addresses)
    for address in local_addresses:
        network = IPv4Network(f"{address}/24", strict=False)
        candidates.update(str(host) for host in network.hosts() if str(host) not in local)
    return sorted(candidates, key=lambda item: int(IPv4Address(item)))


def discover_grbl_hosts(
    port: int = 23,
    *,
    local_addresses: list[str] | None = None,
    connect_timeout: float = 0.18,
) -> list[str]:
    """Find LAN hosts that answer a GRBL real-time status query."""
    addresses = local_addresses if local_addresses is not None else local_ipv4_addresses()
    candidates = subnet_candidates(addresses)
    if not candidates:
        return []
    found: list[str] = []
    with ThreadPoolExecutor(max_workers=64) as executor:
        futures = {
            executor.submit(_is_grbl_endpoint, host, port, connect_timeout): host for host in candidates
        }
        for future in as_completed(futures):
            try:
                if future.result():
                    found.append(futures[future])
            except OSError:
                continue
    return sorted(found, key=lambda item: int(IPv4Address(item)))


def _is_grbl_endpoint(host: str, port: int, timeout: float) -> bool:
    with socket.create_connection((host, port), timeout=timeout) as endpoint:
        endpoint.settimeout(0.7)
        endpoint.sendall(b"?")
        response = endpoint.recv(2048)
    return b"<" in response and b">" in response
