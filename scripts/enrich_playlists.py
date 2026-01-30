#!/usr/bin/env python3
"""Enrich Beatify playlist JSON files with Apple Music and YouTube Music URIs.

Uses the Odesli (song.link) API to look up cross-platform links from Spotify URIs.
No API key required for basic usage.

Usage:
    python3 scripts/enrich_playlists.py [playlist.json ...]

If no files are given, processes all JSON files in custom_components/beatify/playlists/.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple

ODESLI_ENDPOINT = "https://api.song.link/v1-alpha.1/links"
REQUEST_DELAY = 0.15  # seconds between API calls (~6.6 req/s, well within limit)
USER_COUNTRY = "DE"


def spotify_uri_to_url(uri: str) -> Optional[str]:
    """Convert 'spotify:track:ID' to 'https://open.spotify.com/track/ID'."""
    match = re.match(r"spotify:track:(\w+)", uri)
    if match:
        return f"https://open.spotify.com/track/{match.group(1)}"
    return None


def fetch_odesli(spotify_url: str) -> Optional[dict]:
    """Query the Odesli API and return the JSON response, or None on error."""
    params = urllib.parse.urlencode({"url": spotify_url, "userCountry": USER_COUNTRY})
    url = f"{ODESLI_ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"    ⚠  API error: {exc}")
        return None


def extract_apple_music_uri(data: dict) -> str:
    """Extract Apple Music track ID → 'applemusic://track/<id>'."""
    am = data.get("linksByPlatform", {}).get("appleMusic")
    if not am:
        return ""
    # Primary: entityUniqueId "ITUNES_SONG::<id>"
    entity_id = am.get("entityUniqueId", "")
    match = re.search(r"ITUNES_SONG::(\d+)", entity_id)
    if match:
        return f"applemusic://track/{match.group(1)}"
    # Fallback: parse ?i=<id> from the URL
    url = am.get("url", "")
    match = re.search(r"[?&]i=(\d+)", url)
    if match:
        return f"applemusic://track/{match.group(1)}"
    return ""


def extract_youtube_music_url(data: dict) -> str:
    """Extract YouTube Music watch URL."""
    yt = data.get("linksByPlatform", {}).get("youtubeMusic")
    if not yt:
        return ""
    return yt.get("url", "")


def process_playlist(filepath: str) -> Tuple[int, int, int, int]:
    """Enrich a single playlist file. Returns (am_found, am_total, yt_found, yt_total)."""
    print(f"\n📂 Processing: {os.path.basename(filepath)}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    songs = data.get("songs", [])
    total = len(songs)
    am_needed = 0
    yt_needed = 0
    am_found = 0
    yt_found = 0
    api_calls = 0

    for i, song in enumerate(songs, 1):
        need_am = not song.get("uri_apple_music")
        need_yt = not song.get("uri_youtube_music")

        if need_am:
            am_needed += 1
        if need_yt:
            yt_needed += 1

        if not need_am and not need_yt:
            continue

        artist = song.get("artist", "?")
        title = song.get("title", "?")
        uri = song.get("uri", "")
        spotify_url = spotify_uri_to_url(uri)

        if not spotify_url:
            print(f"  [{i:3d}/{total}] ⏭  {artist} – {title} (no valid Spotify URI)")
            continue

        print(f"  [{i:3d}/{total}] 🔍 {artist} – {title}", end="", flush=True)

        if api_calls > 0:
            time.sleep(REQUEST_DELAY)

        result = fetch_odesli(spotify_url)
        api_calls += 1

        if result is None:
            print(" → ❌ API failed")
            continue

        parts = []
        if need_am:
            am_uri = extract_apple_music_uri(result)
            if am_uri:
                song["uri_apple_music"] = am_uri
                am_found += 1
                parts.append("🍎 ✓")
            else:
                parts.append("🍎 ✗")

        if need_yt:
            yt_url = extract_youtube_music_url(result)
            if yt_url:
                song["uri_youtube_music"] = yt_url
                yt_found += 1
                parts.append("🎵 ✓")
            else:
                parts.append("🎵 ✗")

        print(f" → {' '.join(parts)}")

        # Save periodically every 10 API calls
        if api_calls % 10 == 0:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")

    # Final save
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\n  ✅ Saved. Apple Music: {am_found}/{am_needed} enriched | YouTube Music: {yt_found}/{yt_needed} enriched")
    return am_found, am_needed, yt_found, yt_needed


def main():
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        playlist_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "custom_components", "beatify", "playlists",
        )
        files = sorted(
            os.path.join(playlist_dir, f)
            for f in os.listdir(playlist_dir)
            if f.endswith(".json")
        )

    if not files:
        print("No playlist files found.")
        sys.exit(1)

    total_am_found = total_am_needed = total_yt_found = total_yt_needed = 0

    for filepath in files:
        if not os.path.isfile(filepath):
            print(f"⚠  File not found: {filepath}")
            continue
        am_f, am_n, yt_f, yt_n = process_playlist(filepath)
        total_am_found += am_f
        total_am_needed += am_n
        total_yt_found += yt_f
        total_yt_needed += yt_n

    print(f"\n{'='*60}")
    print(f"🏁 Done! Apple Music: {total_am_found}/{total_am_needed} | YouTube Music: {total_yt_found}/{total_yt_needed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
