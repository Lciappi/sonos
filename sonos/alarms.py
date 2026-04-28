"""Alarm clock — list, create, update, delete."""

from __future__ import annotations

import re

from .soap import call, extract


_AC = ("AlarmClock", "/AlarmClock/Control")


_ALARM_RE = re.compile(r"<Alarm\b([^/]*?)/>", re.DOTALL)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def list_alarms(speaker) -> list[dict]:
    """Return every alarm configured in this household.

    Alarms are household-scoped — calling this from any speaker in a
    household returns the same list.
    """
    xml = call(speaker.ip, *_AC, "ListAlarms")
    raw = extract(xml, "CurrentAlarmList") or ""
    raw = _xml_unescape(raw)
    out = []
    for m in _ALARM_RE.finditer(raw):
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        out.append(
            {
                "id": attrs.get("ID", ""),
                "start_time": attrs.get("StartTime", ""),
                "duration": attrs.get("Duration", ""),
                "recurrence": attrs.get("Recurrence", ""),
                "enabled": attrs.get("Enabled", "0") == "1",
                "room_uuid": attrs.get("RoomUUID", ""),
                "program_uri": _xml_unescape(attrs.get("ProgramURI", "")),
                "program_metadata": _xml_unescape(attrs.get("ProgramMetaData", "")),
                "play_mode": attrs.get("PlayMode", "NORMAL"),
                "volume": int(attrs.get("Volume", "0") or 0),
                "include_linked_zones": attrs.get("IncludeLinkedZones", "0") == "1",
            }
        )
    return out


def create_alarm(
    speaker,
    *,
    start_time: str,
    duration: str = "02:00:00",
    recurrence: str = "DAILY",
    enabled: bool = True,
    room_uuid: str | None = None,
    program_uri: str = "",
    program_metadata: str = "",
    play_mode: str = "SHUFFLE",
    volume: int = 25,
    include_linked_zones: bool = False,
) -> str:
    """Create an alarm. Returns the new alarm's ID.

    start_time / duration: "HH:MM:SS"
    recurrence: ONCE | WEEKDAYS | WEEKENDS | DAILY | ON_<digits> (e.g., ON_135)
    """
    xml = call(
        speaker.ip,
        *_AC,
        "CreateAlarm",
        {
            "StartLocalTime": start_time,
            "Duration": duration,
            "Recurrence": recurrence,
            "Enabled": 1 if enabled else 0,
            "RoomUUID": room_uuid or speaker.uuid,
            "ProgramURI": program_uri,
            "ProgramMetaData": program_metadata,
            "PlayMode": play_mode,
            "Volume": int(volume),
            "IncludeLinkedZones": 1 if include_linked_zones else 0,
        },
    )
    return extract(xml, "AssignedID") or ""


def update_alarm(speaker, alarm_id: str, **changes) -> None:
    """Update an alarm in place. Reads current values then patches them.

    Accepts the same keyword args as create_alarm.
    """
    current = next((a for a in list_alarms(speaker) if a["id"] == alarm_id), None)
    if not current:
        raise KeyError(f"alarm {alarm_id!r} not found")
    merged = {**current, **changes}
    call(
        speaker.ip,
        *_AC,
        "UpdateAlarm",
        {
            "ID": alarm_id,
            "StartLocalTime": merged.get("start_time", ""),
            "Duration": merged.get("duration", ""),
            "Recurrence": merged.get("recurrence", ""),
            "Enabled": 1 if merged.get("enabled") else 0,
            "RoomUUID": merged.get("room_uuid", ""),
            "ProgramURI": merged.get("program_uri", ""),
            "ProgramMetaData": merged.get("program_metadata", ""),
            "PlayMode": merged.get("play_mode", "NORMAL"),
            "Volume": int(merged.get("volume", 25)),
            "IncludeLinkedZones": 1 if merged.get("include_linked_zones") else 0,
        },
    )


def delete_alarm(speaker, alarm_id: str) -> None:
    call(speaker.ip, *_AC, "DestroyAlarm", {"ID": alarm_id})


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )
