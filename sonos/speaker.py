"""Sonos Speaker — transport, volume, and now-playing."""

from __future__ import annotations

import re
from urllib import request, error

from .soap import call, extract


_AVT = ("AVTransport", "/MediaRenderer/AVTransport/Control")
_RC = ("RenderingControl", "/MediaRenderer/RenderingControl/Control")


class Speaker:
    """A single Sonos zone player.

    Construct via discovery or directly: ``Speaker(ip="192.168.1.75")``.
    Most fields populate lazily on first attribute access.
    """

    def __init__(self, ip: str, uuid: str = "", household: str = ""):
        self.ip = ip
        self.uuid = uuid
        self.household = household
        self.room_name: str = ""
        self.model_name: str = ""
        self.model_number: str = ""
        self.reachable: bool = False

    # ----- description -----

    def _load_description(self) -> bool:
        """Fetch device_description.xml. Returns True on success."""
        try:
            url = f"http://{self.ip}:1400/xml/device_description.xml"
            with request.urlopen(url, timeout=3) as r:
                xml = r.read().decode("utf-8", errors="replace")
        except error.URLError:
            return False
        for tag in ("roomName", "modelName", "modelNumber"):
            m = re.search(rf"<{tag}>([^<]+)</{tag}>", xml)
            if m:
                setattr(
                    self,
                    {"roomName": "room_name", "modelName": "model_name", "modelNumber": "model_number"}[tag],
                    m.group(1),
                )
        self.reachable = bool(self.room_name)
        return self.reachable

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "ip": self.ip,
            "household": self.household,
            "room_name": self.room_name,
            "model_name": self.model_name,
            "model_number": self.model_number,
        }

    # ----- transport -----

    def play(self) -> None:
        call(self.ip, *_AVT, "Play", {"InstanceID": 0, "Speed": 1})

    def pause(self) -> None:
        call(self.ip, *_AVT, "Pause", {"InstanceID": 0})

    def stop(self) -> None:
        call(self.ip, *_AVT, "Stop", {"InstanceID": 0})

    def next(self) -> None:
        call(self.ip, *_AVT, "Next", {"InstanceID": 0})

    def previous(self) -> None:
        call(self.ip, *_AVT, "Previous", {"InstanceID": 0})

    # ----- volume -----

    def get_volume(self) -> int:
        xml = call(self.ip, *_RC, "GetVolume", {"InstanceID": 0, "Channel": "Master"})
        v = extract(xml, "CurrentVolume")
        return int(v) if v is not None else 0

    def set_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        call(
            self.ip,
            *_RC,
            "SetVolume",
            {"InstanceID": 0, "Channel": "Master", "DesiredVolume": value},
        )

    def get_mute(self) -> bool:
        xml = call(self.ip, *_RC, "GetMute", {"InstanceID": 0, "Channel": "Master"})
        return extract(xml, "CurrentMute") == "1"

    def set_mute(self, mute: bool) -> None:
        call(
            self.ip,
            *_RC,
            "SetMute",
            {"InstanceID": 0, "Channel": "Master", "DesiredMute": 1 if mute else 0},
        )

    # ----- now playing -----

    def transport_state(self) -> str:
        xml = call(self.ip, *_AVT, "GetTransportInfo", {"InstanceID": 0})
        return extract(xml, "CurrentTransportState") or "UNKNOWN"

    def now_playing(self) -> dict:
        info_xml = call(self.ip, *_AVT, "GetPositionInfo", {"InstanceID": 0})
        meta = extract(info_xml, "TrackMetaData") or ""
        uri = extract(info_xml, "TrackURI") or ""
        position = extract(info_xml, "RelTime") or "0:00:00"
        duration = extract(info_xml, "TrackDuration") or "0:00:00"

        title = _didl(meta, "dc:title")
        artist = _didl(meta, "dc:creator") or _didl(meta, "r:albumArtist")
        album = _didl(meta, "upnp:album")
        art_path = _didl(meta, "upnp:albumArtURI")
        art = self._absolute_art(art_path) if art_path else None

        try:
            state = self.transport_state()
        except Exception:
            state = "UNKNOWN"

        return {
            "state": state,
            "title": title,
            "artist": artist,
            "album": album,
            "art": art,
            "position": position,
            "duration": duration,
            "source": _classify_source(uri),
            "uri": uri,
        }

    def _absolute_art(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"http://{self.ip}:1400{path}"


def _didl(meta_xml: str, tag: str) -> str | None:
    if not meta_xml:
        return None
    # \b prevents `album` from matching `albumArtURI` etc.
    m = re.search(
        rf"<{re.escape(tag)}\b[^>]*>(.*?)</{re.escape(tag)}>",
        meta_xml,
        re.DOTALL,
    )
    if not m:
        return None
    val = _xml_unescape(m.group(1).strip())
    return val or None


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _classify_source(uri: str) -> str:
    if not uri:
        return "idle"
    if uri.startswith("x-rincon-stream:"):
        return "line-in"
    if uri.startswith("x-rincon-mp3radio:") or "radio" in uri:
        return "radio"
    if uri.startswith("x-rincon:"):
        return "grouped"
    if uri.startswith("x-rincon-queue:"):
        return "queue"
    if "airplay" in uri.lower() or uri.startswith("x-sonosapi-vli:"):
        return "airplay"
    if "youtube" in uri.lower():
        return "youtube-music"
    if uri.startswith("x-sonos-htastream:"):
        return "tv"
    return "stream"
