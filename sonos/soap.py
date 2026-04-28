"""Minimal SOAP/UPnP client for Sonos. Stdlib only."""

from __future__ import annotations

import re
from urllib import request, error
from xml.sax.saxutils import escape

_ENVELOPE = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>"
    '<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
    "{args}"
    "</u:{action}>"
    "</s:Body>"
    "</s:Envelope>"
)


class SoapError(Exception):
    pass


def call(
    ip: str,
    service: str,
    endpoint: str,
    action: str,
    args: dict | None = None,
    timeout: float = 5.0,
) -> str:
    """Send a SOAP action to a Sonos device. Returns the raw XML response."""
    args = args or {}
    body = "".join(
        f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items()
    )
    payload = _ENVELOPE.format(action=action, service=service, args=body).encode()
    url = f"http://{ip}:1400{endpoint}"
    req = request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SoapError(f"{action} failed: HTTP {e.code} {detail[:200]}") from e
    except error.URLError as e:
        raise SoapError(f"{action} failed: {e.reason}") from e


_TAG_RE = re.compile(r"<(\w+)>([^<]*)</\1>")


def extract(xml: str, tag: str) -> str | None:
    """Extract the first <tag>...</tag> text from a SOAP response."""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
    return _unescape(m.group(1)) if m else None


def extract_all(xml: str) -> dict:
    """Pull every simple <tag>value</tag> pair into a dict."""
    return {k: _unescape(v) for k, v in _TAG_RE.findall(xml)}


def _unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )
