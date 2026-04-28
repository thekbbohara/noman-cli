"""Integration tests for media (Spotify, YouTube, GIF)."""

import pytest


async def test_spotify():
    """Test Spotify client."""
    from core.media.spotify import SpotifyClient
    client = SpotifyClient()
    assert client is not None


async def test_youtube():
    """Test YouTube client."""
    from core.media.youtube import YouTubeClient
    client = YouTubeClient()
    assert client is not None


async def test_gif_search():
    """Test GIF search."""
    from core.media.gif import GIFSearch
    assert GIFSearch is not None
