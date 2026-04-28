"""Zone group topology — which speakers are grouped together, and how."""

from __future__ import annotations

import re

from .soap import call


_ZGT = ("ZoneGroupTopology", "/ZoneGroupTopology/Control")


def groups(speaker) -> list[dict]:
    """Return groups visible to this speaker's household.

    Each group: {coordinator, name, members: [{uuid, name, channel_map,
    is_satellite, pair_partner}], stereo_pair: bool}
    """
    xml = call(speaker.ip, *_ZGT, "GetZoneGroupState")
    state = _unescape(_extract(xml, "ZoneGroupState") or "")
    out = []
    for gm in re.finditer(
        r'<ZoneGroup\b([^>]*?)>(.*?)</ZoneGroup>',
        state,
        re.DOTALL,
    ):
        attrs = _attrs(gm.group(1))
        coord = attrs.get("Coordinator", "")
        members = []
        name = ""
        for member in _iter_zone_members(gm.group(2)):
            if member["uuid"] == coord:
                name = member["name"]
            members.append(member)
        # Annotate stereo-pair partners
        _annotate_pairs(members)
        if members:
            out.append(
                {
                    "coordinator": coord,
                    "name": name,
                    "members": members,
                    "stereo_pair": any(m["pair_partner"] for m in members),
                }
            )
    return out


_MEMBER_OPEN_RE = re.compile(r'<ZoneGroupMember\s([^>]*?)(/?)>', re.DOTALL)


def _iter_zone_members(group_body: str):
    for m in _MEMBER_OPEN_RE.finditer(group_body):
        attrs = _attrs(m.group(1))
        if m.group(2):  # self-closing
            body = ""
        else:
            close = group_body.find("</ZoneGroupMember>", m.end())
            body = group_body[m.end():close] if close > 0 else ""
        if attrs.get("Invisible") == "1":
            # Hidden satellite — surface as a member but flag it.
            yield {
                "uuid": attrs.get("UUID", ""),
                "name": attrs.get("ZoneName", ""),
                "channel_map": attrs.get("ChannelMapSet", "") or attrs.get("HTSatChanMapSet", ""),
                "is_satellite": True,
                "pair_partner": "",
            }
            continue
        yield {
            "uuid": attrs.get("UUID", ""),
            "name": attrs.get("ZoneName", ""),
            "channel_map": attrs.get("ChannelMapSet", ""),
            "is_satellite": False,
            "pair_partner": "",
        }
        # Satellites are sometimes nested:
        for sat in re.finditer(r'<Satellite\b([^/>]*?)/>', body):
            sa = _attrs(sat.group(1))
            yield {
                "uuid": sa.get("UUID", ""),
                "name": sa.get("ZoneName", ""),
                "channel_map": sa.get("ChannelMapSet", "") or sa.get("HTSatChanMapSet", ""),
                "is_satellite": True,
                "pair_partner": "",
            }


def _annotate_pairs(members: list[dict]) -> None:
    """A stereo pair is encoded as ChannelMapSet="UUID_A:LF,LF;UUID_B:RF,RF"."""
    for m in members:
        cm = m.get("channel_map") or ""
        # Look for two UUID:CHANNEL,CHANNEL chunks separated by ';'
        chunks = re.findall(r'(RINCON_[A-F0-9]+):([A-Z]+),', cm)
        if len(chunks) == 2:
            a, b = chunks[0][0], chunks[1][0]
            partner = b if m["uuid"] == a else (a if m["uuid"] == b else "")
            if partner:
                m["pair_partner"] = partner


def _attrs(s: str) -> dict:
    return dict(re.findall(r'(\w+)="([^"]*)"', s))


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
