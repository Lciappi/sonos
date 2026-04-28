"""Sonos dashboard — Flask app.

Only the dashboard layer depends on Flask. The `sonos/` package is pure stdlib
and can be lifted out and dropped into any other project.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from flask import Flask, jsonify, render_template, request

from sonos import Speaker, discover, groups
from sonos.soap import SoapError


app = Flask(__name__)


class SpeakerCache:
    """Discover once, then cache. Re-discover periodically in the background."""

    def __init__(self, ttl: float = 60.0):
        self.ttl = ttl
        self._speakers: list[Speaker] = []
        self._by_uuid: dict[str, Speaker] = {}
        self._last: float = 0.0
        self._lock = threading.Lock()

    def all(self) -> list[Speaker]:
        with self._lock:
            if not self._speakers or (time.time() - self._last) > self.ttl:
                self._refresh_locked()
            return list(self._speakers)

    def get(self, uuid: str) -> Optional[Speaker]:
        if uuid not in self._by_uuid:
            self.all()
        return self._by_uuid.get(uuid)

    def refresh(self) -> list[Speaker]:
        with self._lock:
            self._refresh_locked()
            return list(self._speakers)

    def _refresh_locked(self) -> None:
        found = discover(timeout=2.5)
        self._speakers = found
        self._by_uuid = {s.uuid: s for s in found}
        self._last = time.time()


cache = SpeakerCache()


def _household_groups(speakers: list[Speaker]) -> list[dict]:
    """Run topology once per household; merge results."""
    seen_households: set[str] = set()
    out: list[dict] = []
    for sp in speakers:
        if sp.household in seen_households:
            continue
        seen_households.add(sp.household)
        try:
            for g in groups(sp):
                g["household"] = sp.household
                out.append(g)
        except SoapError:
            continue
    return out


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    speakers = cache.all()
    by_uuid = {s.uuid: s for s in speakers}

    grouped = _household_groups(speakers)
    grouped_uuids: set[str] = set()
    for g in grouped:
        for m in g["members"]:
            grouped_uuids.add(m["uuid"])

    # Solo speakers (in a household whose topology call failed) fall through here.
    for sp in speakers:
        if sp.uuid not in grouped_uuids:
            grouped.append(
                {
                    "household": sp.household,
                    "coordinator": sp.uuid,
                    "name": sp.room_name,
                    "members": [{"uuid": sp.uuid, "name": sp.room_name}],
                }
            )

    payload_groups = []
    for g in grouped:
        coord = by_uuid.get(g["coordinator"])
        if not coord:
            continue
        try:
            np = coord.now_playing()
        except SoapError:
            np = {"state": "ERROR", "title": None, "artist": None, "album": None,
                  "art": None, "position": "0:00:00", "duration": "0:00:00",
                  "source": "idle", "uri": ""}

        members_full = []
        for m in g["members"]:
            sp = by_uuid.get(m["uuid"])
            if not sp:
                continue
            try:
                vol = sp.get_volume()
                muted = sp.get_mute()
            except SoapError:
                vol, muted = 0, False
            members_full.append(
                {
                    **sp.to_dict(),
                    "volume": vol,
                    "muted": muted,
                    "is_coordinator": sp.uuid == g["coordinator"],
                }
            )

        payload_groups.append(
            {
                "coordinator": g["coordinator"],
                "name": g["name"] or (members_full[0]["room_name"] if members_full else ""),
                "household": g.get("household", ""),
                "now_playing": np,
                "members": members_full,
            }
        )

    return jsonify({"groups": payload_groups, "count": len(speakers)})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    speakers = cache.refresh()
    return jsonify({"count": len(speakers)})


def _speaker_or_404(uuid: str) -> tuple[Speaker, None] | tuple[None, tuple]:
    sp = cache.get(uuid)
    if not sp:
        return None, (jsonify({"error": "speaker not found"}), 404)
    return sp, None


@app.route("/api/<uuid>/play", methods=["POST"])
def api_play(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    try:
        sp.play()
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})


@app.route("/api/<uuid>/pause", methods=["POST"])
def api_pause(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    try:
        sp.pause()
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})


@app.route("/api/<uuid>/next", methods=["POST"])
def api_next(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    try:
        sp.next()
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})


@app.route("/api/<uuid>/previous", methods=["POST"])
def api_previous(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    try:
        sp.previous()
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})


@app.route("/api/<uuid>/volume", methods=["POST"])
def api_volume(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        value = int(data.get("volume", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "volume must be int 0-100"}), 400
    if not 0 <= value <= 100:
        return jsonify({"error": "volume must be 0-100"}), 400
    try:
        sp.set_volume(value)
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True, "volume": value})


@app.route("/api/<uuid>/mute", methods=["POST"])
def api_mute(uuid):
    sp, err = _speaker_or_404(uuid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    muted = bool(data.get("muted", False))
    try:
        sp.set_mute(muted)
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True, "muted": muted})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
