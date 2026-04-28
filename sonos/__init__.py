"""Self-contained Sonos control library.

Pure stdlib. No third-party dependencies. Drop the `sonos/` folder into any
project and it works.

    from sonos import discover, Speaker

    for sp in discover():
        print(sp.room_name, sp.now_playing())
        sp.set_volume(20)
"""

from .discovery import discover, discover_one
from .speaker import Speaker
from .topology import groups

__all__ = ["discover", "discover_one", "Speaker", "groups"]
