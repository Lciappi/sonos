"""Zone group topology — which speakers are grouped together."""

from __future__ import annotations

import re

from .soap import call


_ZGT = ("ZoneGroupTopology", "/ZoneGroupTopology/Control")


def groups(speaker) -> list[dict]:
    """Query any speaker in a household; returns the full group layout.

    Each entry: {coordinator_uuid, members: [uuid, ...], name}
    """
    xml = call(speaker.ip, *_ZGT, "GetZoneGroupState")
    state = _unescape(_extract(xml, "ZoneGroupState") or "")
    out = []
    for gm in re.finditer(
        r'<ZoneGroup[^>]*Coordinator="([^"]+)"[^>]*>(.*?)</ZoneGroup>',
        state,
        re.DOTALL,
    ):
        coord = gm.group(1)
        members = []
        name = ""
        for mm in re.finditer(
            r'<ZoneGroupMember[^>]*UUID="([^"]+)"[^>]*ZoneName="([^"]+)"',
            gm.group(2),
        ):
            members.append({"uuid": mm.group(1), "name": mm.group(2)})
            if mm.group(1) == coord:
                name = mm.group(2)
        if members:
            out.append({"coordinator": coord, "name": name, "members": members})
    return out


def _extract(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
    return m.group(1) if m else None


def _unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )
