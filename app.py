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
from sonos import alarms as alarms_mod
from sonos import content as content_mod
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

    def household_speaker(self, household: str) -> Optional[Speaker]:
        for sp in self.all():
            if sp.household == household:
                return sp
        return None

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


def _safe(fn, default=None):
    try:
        return fn()
    except SoapError:
        return default


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

    for sp in speakers:
        if sp.uuid not in grouped_uuids:
            grouped.append(
                {
                    "household": sp.household,
                    "coordinator": sp.uuid,
                    "name": sp.room_name,
                    "members": [
                        {
                            "uuid": sp.uuid,
                            "name": sp.room_name,
                            "is_satellite": False,
                            "pair_partner": "",
                        }
                    ],
                    "stereo_pair": False,
                }
            )

    payload_groups = []
    for g in grouped:
        coord = by_uuid.get(g["coordinator"])
        if not coord:
            continue
        np = _safe(coord.now_playing, default={
            "state": "ERROR", "title": None, "artist": None, "album": None,
            "art": None, "position": "0:00:00", "duration": "0:00:00",
            "source": "idle", "uri": "",
        })
        play_mode = _safe(coord.get_play_mode, default="NORMAL")
        crossfade = _safe(coord.get_crossfade, default=False)
        sleep_remaining = _safe(coord.get_sleep_timer, default=0)

        members_full = []
        for m in g["members"]:
            sp = by_uuid.get(m["uuid"])
            if not sp:
                # Satellite/invisible member — surface what we can.
                members_full.append({
                    "uuid": m["uuid"],
                    "ip": "",
                    "household": g.get("household", ""),
                    "room_name": m.get("name", ""),
                    "model_name": "",
                    "model_number": "",
                    "volume": 0,
                    "muted": False,
                    "is_coordinator": m["uuid"] == g["coordinator"],
                    "is_satellite": m.get("is_satellite", False),
                    "pair_partner": m.get("pair_partner", ""),
                })
                continue
            members_full.append({
                **sp.to_dict(),
                "volume": _safe(sp.get_volume, default=0),
                "muted": _safe(sp.get_mute, default=False),
                "is_coordinator": sp.uuid == g["coordinator"],
                "is_satellite": m.get("is_satellite", False),
                "pair_partner": m.get("pair_partner", ""),
            })

        payload_groups.append({
            "coordinator": g["coordinator"],
            "name": g["name"] or (members_full[0]["room_name"] if members_full else ""),
            "household": g.get("household", ""),
            "now_playing": np,
            "play_mode": play_mode,
            "crossfade": crossfade,
            "sleep_remaining": sleep_remaining,
            "stereo_pair": g.get("stereo_pair", False),
            "members": members_full,
        })

    households = sorted({g["household"] for g in payload_groups if g["household"]})
    return jsonify({"groups": payload_groups, "count": len(speakers), "households": households})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    speakers = cache.refresh()
    return jsonify({"count": len(speakers)})


def _speaker_or_404(uuid: str):
    sp = cache.get(uuid)
    if not sp:
        return None, (jsonify({"error": "speaker not found"}), 404)
    return sp, None


def _wrap(fn, *a, **kw):
    """Run a Speaker method, returning (response, status)."""
    try:
        result = fn(*a, **kw)
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"ok": True}), 200
    return jsonify({"ok": True, "result": result}), 200


# ----- transport / volume / mute -----

@app.post("/api/<uuid>/play")
def api_play(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(sp.play)

@app.post("/api/<uuid>/pause")
def api_pause(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(sp.pause)

@app.post("/api/<uuid>/next")
def api_next(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(sp.next)

@app.post("/api/<uuid>/previous")
def api_previous(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(sp.previous)

@app.post("/api/<uuid>/volume")
def api_volume(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    try:
        value = int(data.get("volume", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "volume must be int 0-100"}), 400
    if not 0 <= value <= 100:
        return jsonify({"error": "volume must be 0-100"}), 400
    return _wrap(sp.set_volume, value)

@app.post("/api/<uuid>/mute")
def api_mute(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_mute, bool(data.get("muted", False)))


# ----- seek -----

@app.post("/api/<uuid>/seek")
def api_seek(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    if "track" in data:
        return _wrap(sp.seek_track, int(data["track"]))
    pos = data.get("position", "")
    if not pos:
        return jsonify({"error": "position or track required"}), 400
    return _wrap(sp.seek_time, str(pos))


# ----- play modes & crossfade -----

@app.post("/api/<uuid>/play_mode")
def api_play_mode(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_play_mode, str(data.get("mode", "NORMAL")))

@app.post("/api/<uuid>/crossfade")
def api_crossfade(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_crossfade, bool(data.get("on", False)))


# ----- sleep timer -----

@app.post("/api/<uuid>/sleep")
def api_sleep(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    try:
        seconds = int(data.get("seconds", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "seconds must be int"}), 400
    return _wrap(sp.set_sleep_timer, seconds)


# ----- EQ -----

@app.get("/api/<uuid>/eq")
def api_eq_get(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    return jsonify({
        "bass": _safe(sp.get_bass, default=0),
        "treble": _safe(sp.get_treble, default=0),
        "loudness": _safe(sp.get_loudness, default=False),
        "balance": _safe(sp.get_balance, default=0),
    })

@app.post("/api/<uuid>/bass")
def api_bass(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_bass, int(data.get("value", 0)))

@app.post("/api/<uuid>/treble")
def api_treble(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_treble, int(data.get("value", 0)))

@app.post("/api/<uuid>/loudness")
def api_loudness(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_loudness, bool(data.get("on", False)))

@app.post("/api/<uuid>/balance")
def api_balance(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(sp.set_balance, int(data.get("value", 0)))


# ----- grouping -----

@app.post("/api/<uuid>/group/join")
def api_group_join(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    coord = str(data.get("coordinator", ""))
    if not coord:
        return jsonify({"error": "coordinator required"}), 400
    return _wrap(sp.join, coord)

@app.post("/api/<uuid>/group/unjoin")
def api_group_unjoin(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(sp.unjoin)

@app.post("/api/<uuid>/group/everywhere")
def api_group_everywhere(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    targets = [s for s in cache.all() if s.household == sp.household and s.uuid != sp.uuid]
    errors = []
    for t in targets:
        try:
            t.join(sp.uuid)
        except SoapError as e:
            errors.append(f"{t.room_name}: {e}")
    return jsonify({"ok": not errors, "joined": [t.room_name for t in targets], "errors": errors})


# ----- queue -----

@app.get("/api/<uuid>/queue")
def api_queue_get(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    try:
        items = content_mod.get_queue(sp)
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"items": items})

@app.post("/api/<uuid>/queue/play")
def api_queue_play(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    pos = int(data.get("position", 1))
    return _wrap(content_mod.play_from_queue, sp, pos)

@app.post("/api/<uuid>/queue/clear")
def api_queue_clear(uuid):
    sp, err = _speaker_or_404(uuid);  return err or _wrap(content_mod.remove_all, sp)

@app.post("/api/<uuid>/queue/remove")
def api_queue_remove(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    pos = int(data.get("position", 0))
    if pos < 1:
        return jsonify({"error": "position must be >= 1"}), 400
    return _wrap(content_mod.remove_track, sp, pos)

@app.post("/api/<uuid>/queue/reorder")
def api_queue_reorder(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    return _wrap(
        content_mod.reorder, sp,
        int(data.get("start", 0)),
        int(data.get("count", 1)),
        int(data.get("before", 0)),
    )

@app.post("/api/<uuid>/queue/save")
def api_queue_save(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    return _wrap(content_mod.save_queue_as, sp, title)


# ----- favorites & playlists -----

@app.get("/api/<uuid>/favorites")
def api_favorites(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    try:
        return jsonify({"items": content_mod.list_favorites(sp)})
    except SoapError as e:
        return jsonify({"error": str(e)}), 502

@app.get("/api/<uuid>/playlists")
def api_playlists(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    try:
        return jsonify({"items": content_mod.list_sonos_playlists(sp)})
    except SoapError as e:
        return jsonify({"error": str(e)}), 502

@app.post("/api/<uuid>/play_favorite")
def api_play_favorite(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    fav = {"uri": data.get("uri", ""), "metadata": data.get("metadata", ""), "is_container": bool(data.get("is_container"))}
    if not fav["uri"]:
        return jsonify({"error": "uri required"}), 400
    return _wrap(content_mod.play_favorite, sp, fav)

@app.post("/api/<uuid>/play_playlist")
def api_play_playlist(uuid):
    sp, err = _speaker_or_404(uuid)
    if err: return err
    data = request.get_json(silent=True) or {}
    pl = {"uri": data.get("uri", ""), "metadata": data.get("metadata", ""), "is_container": True}
    if not pl["uri"]:
        return jsonify({"error": "uri required"}), 400
    return _wrap(content_mod.play_playlist, sp, pl)


# ----- alarms (per household) -----

@app.get("/api/alarms")
def api_alarms_list():
    speakers = cache.all()
    seen = set()
    out = []
    for sp in speakers:
        if sp.household in seen:
            continue
        seen.add(sp.household)
        try:
            for a in alarms_mod.list_alarms(sp):
                a["household"] = sp.household
                out.append(a)
        except SoapError:
            continue
    return jsonify({"items": out})

@app.post("/api/alarms")
def api_alarms_create():
    data = request.get_json(silent=True) or {}
    room_uuid = str(data.get("room_uuid", ""))
    sp, err = _speaker_or_404(room_uuid)
    if err: return err
    try:
        alarm_id = alarms_mod.create_alarm(
            sp,
            start_time=str(data.get("start_time", "07:00:00")),
            duration=str(data.get("duration", "01:00:00")),
            recurrence=str(data.get("recurrence", "DAILY")),
            enabled=bool(data.get("enabled", True)),
            room_uuid=room_uuid,
            program_uri=str(data.get("program_uri", "")),
            program_metadata=str(data.get("program_metadata", "")),
            play_mode=str(data.get("play_mode", "SHUFFLE")),
            volume=int(data.get("volume", 25)),
            include_linked_zones=bool(data.get("include_linked_zones", False)),
        )
    except SoapError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True, "id": alarm_id})

@app.patch("/api/alarms/<alarm_id>")
def api_alarms_update(alarm_id):
    data = request.get_json(silent=True) or {}
    # Find any speaker in the right household
    households_seen = set()
    for sp in cache.all():
        if sp.household in households_seen:
            continue
        households_seen.add(sp.household)
        try:
            existing = alarms_mod.list_alarms(sp)
        except SoapError:
            continue
        if any(a["id"] == alarm_id for a in existing):
            try:
                alarms_mod.update_alarm(sp, alarm_id, **data)
            except (SoapError, KeyError) as e:
                return jsonify({"error": str(e)}), 502
            return jsonify({"ok": True})
    return jsonify({"error": "alarm not found"}), 404

@app.delete("/api/alarms/<alarm_id>")
def api_alarms_delete(alarm_id):
    for sp in cache.all():
        try:
            alarms_mod.delete_alarm(sp, alarm_id)
            return jsonify({"ok": True})
        except SoapError:
            continue
    return jsonify({"error": "could not delete"}), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
