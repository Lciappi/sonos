"""Queue, favorites, and saved-playlists via the ContentDirectory service."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from .soap import call, extract


_CD = ("ContentDirectory", "/MediaServer/ContentDirectory/Control")
_AVT = ("AVTransport", "/MediaRenderer/AVTransport/Control")


# ---------- queue ----------

def get_queue(speaker, start: int = 0, count: int = 200) -> list[dict]:
    """Return the current queue as a list of {position, title, artist, album, art, uri}."""
    xml = call(
        speaker.ip,
        *_CD,
        "Browse",
        {
            "ObjectID": "Q:0",
            "BrowseFlag": "BrowseDirectChildren",
            "Filter": "*",
            "StartingIndex": start,
            "RequestedCount": count,
            "SortCriteria": "",
        },
    )
    didl = _xml_unescape(extract(xml, "Result") or "")
    return _parse_didl_items(didl, speaker, start)


def add_uri_to_queue(
    speaker,
    uri: str,
    metadata: str = "",
    position: int = 0,
    as_next: bool = False,
) -> dict:
    xml = call(
        speaker.ip,
        *_AVT,
        "AddURIToQueue",
        {
            "InstanceID": 0,
            "EnqueuedURI": uri,
            "EnqueuedURIMetaData": metadata,
            "DesiredFirstTrackNumberEnqueued": int(position),
            "EnqueueAsNext": 1 if as_next else 0,
        },
    )
    return {
        "first_track": int(extract(xml, "FirstTrackNumberEnqueued") or 0),
        "added": int(extract(xml, "NumTracksAdded") or 0),
        "new_length": int(extract(xml, "NewQueueLength") or 0),
    }


def remove_track(speaker, position: int) -> None:
    """Remove a track from the queue. Position is 1-based per Sonos convention."""
    call(
        speaker.ip,
        *_AVT,
        "RemoveTrackFromQueue",
        {"InstanceID": 0, "ObjectID": f"Q:0/{int(position)}", "UpdateID": 0},
    )


def remove_all(speaker) -> None:
    call(speaker.ip, *_AVT, "RemoveAllTracksFromQueue", {"InstanceID": 0})


def reorder(speaker, start: int, count: int, insert_before: int) -> None:
    call(
        speaker.ip,
        *_AVT,
        "ReorderTracksInQueue",
        {
            "InstanceID": 0,
            "StartingIndex": int(start),
            "NumberOfTracks": int(count),
            "InsertBefore": int(insert_before),
            "UpdateID": 0,
        },
    )


def save_queue_as(speaker, title: str) -> str:
    """Save the current queue as a Sonos playlist. Returns the new playlist's ID."""
    xml = call(
        speaker.ip,
        *_AVT,
        "SaveQueue",
        {"InstanceID": 0, "Title": title, "ObjectID": ""},
    )
    return extract(xml, "AssignedObjectID") or ""


# ---------- favorites & saved playlists ----------

def list_favorites(speaker) -> list[dict]:
    return _browse_collection(speaker, "FV:2")


def list_sonos_playlists(speaker) -> list[dict]:
    return _browse_collection(speaker, "SQ:")


def _browse_collection(speaker, object_id: str, count: int = 500) -> list[dict]:
    xml = call(
        speaker.ip,
        *_CD,
        "Browse",
        {
            "ObjectID": object_id,
            "BrowseFlag": "BrowseDirectChildren",
            "Filter": "*",
            "StartingIndex": 0,
            "RequestedCount": count,
            "SortCriteria": "",
        },
    )
    didl = _xml_unescape(extract(xml, "Result") or "")
    return _parse_didl_items(didl, speaker)


# ---------- playback helpers ----------

def play_uri(speaker, uri: str, metadata: str = "") -> None:
    """Set the AV transport URI and start playing. Use this for favorites/streams."""
    call(
        speaker.ip,
        *_AVT,
        "SetAVTransportURI",
        {"InstanceID": 0, "CurrentURI": uri, "CurrentURIMetaData": metadata},
    )
    speaker.play()


def play_from_queue(speaker, position: int = 1) -> None:
    """Switch to the queue and start playing at the given (1-based) position."""
    queue_uri = f"x-rincon-queue:{speaker.uuid}#0"
    call(
        speaker.ip,
        *_AVT,
        "SetAVTransportURI",
        {"InstanceID": 0, "CurrentURI": queue_uri, "CurrentURIMetaData": ""},
    )
    speaker.seek_track(position)
    speaker.play()


def play_favorite(speaker, favorite: dict) -> None:
    """Take an entry from list_favorites() and start playing it."""
    _play_resolved(speaker, favorite)


def play_playlist(speaker, playlist: dict) -> None:
    """Take an entry from list_sonos_playlists() and start playing it.

    Playlists are containers — load them into the queue, then play.
    """
    speaker.unjoin() if False else None  # no-op; documented for clarity
    if playlist.get("is_container"):
        remove_all(speaker)
        add_uri_to_queue(speaker, playlist["uri"], playlist.get("metadata", ""), position=0)
        play_from_queue(speaker, 1)
    else:
        _play_resolved(speaker, playlist)


def _play_resolved(speaker, item: dict) -> None:
    uri = item.get("uri") or ""
    meta = item.get("metadata") or ""
    if not uri:
        raise ValueError("item has no URI")
    if item.get("is_container"):
        remove_all(speaker)
        add_uri_to_queue(speaker, uri, meta, position=0)
        play_from_queue(speaker, 1)
    else:
        play_uri(speaker, uri, meta)


# ---------- DIDL parsing ----------

_ITEM_RE = re.compile(r"<(item|container)\b([^>]*)>(.*?)</\1>", re.DOTALL)
_RES_RE = re.compile(r"<res\b[^>]*>(.*?)</res>", re.DOTALL)


def _parse_didl_items(didl: str, speaker, start: int = 0) -> list[dict]:
    if not didl:
        return []
    out = []
    for i, m in enumerate(_ITEM_RE.finditer(didl)):
        kind, attrs, body = m.group(1), m.group(2), m.group(3)
        item_id_m = re.search(r'id="([^"]+)"', attrs)
        title = _xml_unescape(_inner(body, "dc:title") or "")
        creator = _xml_unescape(_inner(body, "dc:creator") or "")
        album = _xml_unescape(_inner(body, "upnp:album") or "")
        art_path = _xml_unescape(_inner(body, "upnp:albumArtURI") or "")
        res = _RES_RE.search(body)
        uri = _xml_unescape(res.group(1) if res else "")
        # The desc/metadata element used by SetAVTransportURI:
        meta_resmd = _inner(body, "r:resMD")
        # Fall back to wrapping the original DIDL fragment as metadata.
        metadata = _xml_unescape(meta_resmd) if meta_resmd else _wrap_didl_item(m.group(0))

        out.append(
            {
                "id": item_id_m.group(1) if item_id_m else "",
                "position": start + i + 1,  # 1-based
                "title": title or None,
                "artist": creator or None,
                "album": album or None,
                "art": speaker._absolute_art(art_path) if art_path else None,
                "uri": uri,
                "metadata": metadata,
                "is_container": kind == "container",
            }
        )
    return out


def _inner(body: str, tag: str) -> str | None:
    m = re.search(
        rf"<{re.escape(tag)}\b[^>]*>(.*?)</{re.escape(tag)}>",
        body,
        re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _wrap_didl_item(item_xml: str) -> str:
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        + item_xml
        + "</DIDL-Lite>"
    )


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )
