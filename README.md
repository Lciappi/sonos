# sonos

A small web dashboard for controlling Sonos speakers on the local network.

## Usage

### Run the dashboard

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open http://127.0.0.1:5050.

The dashboard auto-discovers every Sonos speaker on the LAN (across multiple
Sonos households), groups them as the Sonos app does, and gives you:

- now-playing track, artist, album art, source
- play / pause / next / previous
- per-speaker volume sliders and mute
- a re-scan button for when speakers come and go

It polls every 2.5 seconds and pauses polling while you're dragging a slider
so the UI doesn't fight you.

### Use the Sonos library directly

The `sonos/` package is pure stdlib and has no dependency on Flask. Drop it
into any Python project:

```python
from sonos import discover, groups

for sp in discover():
    print(sp.room_name, sp.now_playing())
    sp.set_volume(20)

# Group topology (which speakers are paired together)
for g in groups(discover()[0]):
    print(g["name"], "->", [m["name"] for m in g["members"]])
```

`Speaker` exposes: `play`, `pause`, `stop`, `next`, `previous`,
`get_volume` / `set_volume`, `get_mute` / `set_mute`, `transport_state`,
`now_playing`.

### Picking music

Sonos doesn't expose YouTube Music browse over the local UPnP API, so this
dashboard doesn't include search. Pick songs in the YouTube Music app, the
Sonos app, or AirPlay from your Mac — the dashboard will show whatever's
playing and handle transport, volume, and groups regardless of source.

## About

This repo is two things glued together:

**`sonos/`** — a small, stdlib-only Sonos client. SSDP discovery, SOAP/UPnP
calls, transport, volume, and zone-group topology. No third-party
dependencies. Self-contained so it can be lifted into any Python project.

**`app.py` + `templates/` + `static/`** — a Flask web dashboard layered on
top. Flask is the only third-party dependency, and only the dashboard uses
it; the Sonos package never imports Flask.

### Layout

```
sonos/
├── sonos/                  pure stdlib Sonos library
│   ├── __init__.py
│   ├── soap.py             SOAP/UPnP client
│   ├── discovery.py        SSDP M-SEARCH
│   ├── speaker.py          transport + volume + now-playing
│   └── topology.py         zone groups
├── app.py                  Flask dashboard (the only Flask consumer)
├── templates/index.html
├── static/{style.css, app.js}
└── requirements.txt        Flask
```

### How it talks to Sonos

Every Sonos device speaks UPnP on TCP port 1400. Discovery is an SSDP
M-SEARCH on UDP 239.255.255.250:1900 with `ST: urn:schemas-upnp-org:device:ZonePlayer:1`.
Each responding device exposes services at well-known endpoints
(`/MediaRenderer/AVTransport/Control`, `/MediaRenderer/RenderingControl/Control`,
`/ZoneGroupTopology/Control`); SOAP envelopes are POSTed there. No Sonos
cloud account, no API keys, no internet — everything is on the LAN.
