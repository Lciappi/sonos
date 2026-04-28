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

    # ----- EQ (bass / treble / loudness / balance) -----

    def get_bass(self) -> int:
        xml = call(self.ip, *_RC, "GetBass", {"InstanceID": 0})
        v = extract(xml, "CurrentBass")
        return int(v) if v is not None else 0

    def set_bass(self, value: int) -> None:
        value = max(-10, min(10, int(value)))
        call(self.ip, *_RC, "SetBass", {"InstanceID": 0, "DesiredBass": value})

    def get_treble(self) -> int:
        xml = call(self.ip, *_RC, "GetTreble", {"InstanceID": 0})
        v = extract(xml, "CurrentTreble")
        return int(v) if v is not None else 0

    def set_treble(self, value: int) -> None:
        value = max(-10, min(10, int(value)))
        call(self.ip, *_RC, "SetTreble", {"InstanceID": 0, "DesiredTreble": value})

    def get_loudness(self) -> bool:
        xml = call(self.ip, *_RC, "GetLoudness", {"InstanceID": 0, "Channel": "Master"})
        return extract(xml, "CurrentLoudness") == "1"

    def set_loudness(self, on: bool) -> None:
        call(
            self.ip,
            *_RC,
            "SetLoudness",
            {"InstanceID": 0, "Channel": "Master", "DesiredLoudness": 1 if on else 0},
        )

    def get_balance(self) -> int:
        """Return -100 (full left) … 0 (centered) … +100 (full right)."""
        lf = call(self.ip, *_RC, "GetVolume", {"InstanceID": 0, "Channel": "LF"})
        rf = call(self.ip, *_RC, "GetVolume", {"InstanceID": 0, "Channel": "RF"})
        try:
            lv = int(extract(lf, "CurrentVolume") or "100")
            rv = int(extract(rf, "CurrentVolume") or "100")
        except ValueError:
            return 0
        return rv - lv  # -100..+100

    def set_balance(self, value: int) -> None:
        value = max(-100, min(100, int(value)))
        lf = 100 - max(0, value)
        rf = 100 + min(0, value)
        call(self.ip, *_RC, "SetVolume", {"InstanceID": 0, "Channel": "LF", "DesiredVolume": lf})
        call(self.ip, *_RC, "SetVolume", {"InstanceID": 0, "Channel": "RF", "DesiredVolume": rf})

    # ----- play mode (shuffle / repeat) and crossfade -----

    PLAY_MODES = (
        "NORMAL",
        "REPEAT_ALL",
        "REPEAT_ONE",
        "SHUFFLE_NOREPEAT",
        "SHUFFLE",
        "SHUFFLE_REPEAT_ONE",
    )

    def get_play_mode(self) -> str:
        xml = call(self.ip, *_AVT, "GetTransportSettings", {"InstanceID": 0})
        return extract(xml, "PlayMode") or "NORMAL"

    def set_play_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode not in self.PLAY_MODES:
            raise ValueError(f"unknown play mode {mode!r}")
        call(self.ip, *_AVT, "SetPlayMode", {"InstanceID": 0, "NewPlayMode": mode})

    def get_crossfade(self) -> bool:
        xml = call(self.ip, *_AVT, "GetCrossfadeMode", {"InstanceID": 0})
        return extract(xml, "CrossfadeMode") == "1"

    def set_crossfade(self, on: bool) -> None:
        call(
            self.ip,
            *_AVT,
            "SetCrossfadeMode",
            {"InstanceID": 0, "CrossfadeMode": 1 if on else 0},
        )

    # ----- seek -----

    def seek_time(self, hms: str) -> None:
        """Seek to position in current track. Format: 'H:MM:SS' or 'MM:SS'."""
        if hms.count(":") == 1:
            hms = "0:" + hms
        call(self.ip, *_AVT, "Seek", {"InstanceID": 0, "Unit": "REL_TIME", "Target": hms})

    def seek_track(self, track_number: int) -> None:
        call(
            self.ip,
            *_AVT,
            "Seek",
            {"InstanceID": 0, "Unit": "TRACK_NR", "Target": int(track_number)},
        )

    # ----- sleep timer -----

    def get_sleep_timer(self) -> int:
        """Remaining sleep timer in seconds. 0 if disabled."""
        xml = call(self.ip, *_AVT, "GetRemainingSleepTimerDuration", {"InstanceID": 0})
        hms = extract(xml, "RemainingSleepTimerDuration") or ""
        return _hms_to_seconds(hms)

    def set_sleep_timer(self, seconds: int) -> None:
        """Set sleep timer. Pass 0 to cancel."""
        if seconds <= 0:
            duration = ""
        else:
            duration = _seconds_to_hms(seconds)
        call(
            self.ip,
            *_AVT,
            "ConfigureSleepTimer",
            {"InstanceID": 0, "NewSleepTimerDuration": duration},
        )

    # ----- grouping -----

    def join(self, coordinator_uuid: str) -> None:
        """Join the group whose coordinator has the given UUID."""
        call(
            self.ip,
            *_AVT,
            "SetAVTransportURI",
            {
                "InstanceID": 0,
                "CurrentURI": f"x-rincon:{coordinator_uuid}",
                "CurrentURIMetaData": "",
            },
        )

    def unjoin(self) -> None:
        """Leave the current group, becoming a standalone coordinator."""
        call(self.ip, *_AVT, "BecomeCoordinatorOfStandaloneGroup", {"InstanceID": 0})

    # ----- now playing -----

    def transport_state(self) -> str:
        xml = call(self.ip, *_AVT, "GetTransportInfo", {"InstanceID": 0})
        return extract(xml, "CurrentTransportState") or "UNKNOWN"

    def get_media_info(self) -> dict:
        """Return what's loaded into the AV transport (URI + metadata).

        Distinct from now_playing()/GetPositionInfo: this returns the
        *container* URI (e.g. queue, radio stream, favorite) rather than the
        currently-playing track URI within it.
        """
        xml = call(self.ip, *_AVT, "GetMediaInfo", {"InstanceID": 0})
        return {
            "uri": extract(xml, "CurrentURI") or "",
            "metadata": extract(xml, "CurrentURIMetaData") or "",
        }

    def set_av_transport_uri(self, uri: str, metadata: str = "") -> None:
        call(
            self.ip,
            *_AVT,
            "SetAVTransportURI",
            {"InstanceID": 0, "CurrentURI": uri, "CurrentURIMetaData": metadata},
        )

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


def _hms_to_seconds(hms: str) -> int:
    if not hms or hms == "NOT_IMPLEMENTED":
        return 0
    parts = hms.split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = (int(p) for p in parts)
            return m * 60 + s
    except ValueError:
        return 0
    return 0


def _seconds_to_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


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
