"""SSDP discovery for Sonos ZonePlayers."""

from __future__ import annotations

import re
import socket
from typing import Iterator

_SSDP_ADDR = "239.255.255.250"
_SSDP_PORT = 1900
_ST = "urn:schemas-upnp-org:device:ZonePlayer:1"

_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    f"ST: {_ST}\r\n"
    "\r\n"
).encode()


def _parse(payload: str) -> dict:
    out: dict = {}
    for line in payload.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().upper()] = v.strip()
    return out


def discover(timeout: float = 3.0) -> list:
    """Return a list of Speaker instances on the LAN.

    Imports Speaker lazily to avoid a circular import.
    """
    from .speaker import Speaker

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    sock.sendto(_MSEARCH, (_SSDP_ADDR, _SSDP_PORT))

    seen: dict[str, Speaker] = {}
    try:
        while True:
            data, addr = sock.recvfrom(2048)
            headers = _parse(data.decode("utf-8", errors="replace"))
            usn = headers.get("USN", "")
            m = re.search(r"uuid:([^:]+)", usn)
            if not m:
                continue
            uuid = m.group(1)
            if uuid in seen:
                continue
            seen[uuid] = Speaker(
                ip=addr[0],
                uuid=uuid,
                household=headers.get("X-RINCON-HOUSEHOLD", ""),
            )
    except socket.timeout:
        pass
    finally:
        sock.close()

    reachable = []
    for sp in seen.values():
        if sp._load_description():
            reachable.append(sp)
    return reachable


def discover_one(timeout: float = 3.0):
    speakers = discover(timeout=timeout)
    return speakers[0] if speakers else None


def _iter_responses(timeout: float) -> Iterator[tuple]:
    """Internal helper for tests/diagnostics."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    sock.sendto(_MSEARCH, (_SSDP_ADDR, _SSDP_PORT))
    try:
        while True:
            data, addr = sock.recvfrom(2048)
            yield addr, data.decode("utf-8", errors="replace")
    except socket.timeout:
        return
    finally:
        sock.close()
