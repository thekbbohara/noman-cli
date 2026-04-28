"""Media integration module.

Provides Spotify, YouTube, and GIF search/download functionality.
"""

from __future__ import annotations

from core.media.spotify import SpotifyClient
from core.media.youtube import YouTubeClient
from core.media.gif import GIFClient

__all__ = [
    "SpotifyClient",
    "YouTubeClient",
    "GIFClient",
]
