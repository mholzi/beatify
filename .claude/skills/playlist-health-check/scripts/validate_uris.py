#!/usr/bin/env python3
import json, os, re, sys, time, unicodedata, urllib.request, urllib.error
from difflib import SequenceMatcher

# User-maintained deny-list for URIs confirmed dead in real Music Assistant
# playback, even though public provider APIs still report them as healthy.
# See known_bad_uris.json for the rationale.
_DENY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "known_bad_uris.json")
try:
    with open(_DENY_PATH) as _f:
        _DENYLIST = json.load(_f).get("uris", {})
except (OSError, json.JSONDecodeError):
    _DENYLIST = {}

PATTERNS = {
    "spotify":       re.compile(r"^spotify:track:([a-zA-Z0-9]{22})$"),
    "youtube_music": re.compile(r"^https://music\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})$"),
    "deezer":        re.compile(r"^deezer://track/(\d+)$"),
    "tidal":         re.compile(r"^tidal://track/(\d+)$"),
    "apple_music":   re.compile(r"^applemusic://track/(\d+)$"),
}

def detect_provider(uri):
    for p, pat in PATTERNS.items():
        m = pat.match(uri)
        if m: return p, m.group(1)
    return "unknown", None

# Codes that mean "the provider is overloaded / throttling us", not "the track
# is gone". Under a long run (1000+ sequential lookups) Spotify's oEmbed starts
# answering 404/5xx to healthy tracks, so every one of these is retried with
# backoff before it is allowed to count as a defect. A 404 that survives all
# retries is treated as genuinely dead.
TRANSIENT_CODES = {408, 425, 429, 500, 502, 503, 504}
RETRY_BACKOFF = (1.0, 4.0, 15.0)   # sleep before attempt 2, 3, 4

def http_json(url, headers=None, timeout=10, retry_404=False):
    """GET a JSON endpoint with retry + backoff.

    Returns (data, code, transient):
      data      parsed JSON, or None on failure
      code      last HTTP status seen (None if the request never completed)
      transient True when the failure looks like throttling / provider
                flakiness rather than a missing resource — callers must NOT
                report those as dead or wrong_track.
    """
    hdrs = headers or {"User-Agent": "Beatify-HealthCheck/1.0"}
    code = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status == 200:
                    return json.loads(r.read().decode()), 200, False
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
            # Permanent for this provider → answer immediately, don't burn retries.
            if code not in TRANSIENT_CODES and not (retry_404 and code == 404):
                return None, code, False
        except Exception:
            code = None   # timeout / DNS / reset — worth retrying
        if attempt < len(RETRY_BACKOFF):
            time.sleep(RETRY_BACKOFF[attempt])
    # Exhausted. A 404 that kept 404-ing across ~20s is a real miss; anything
    # else (429, 5xx, connection failures) is the provider, not the track.
    return None, code, code != 404

_NOISE_RE = re.compile(
    r'(?i)'
    r'[\-–—]\s*(?:official\s+)?(?:video|audio|lyric|lyrics|clip|music)\s*(?:version|oficial|hd|hq)?'
    r'|[\-–—]\s*(?:versión|version)\b.*'
    r'|\b(?:official|oficiala?)\s+(?:video|audio|lyric|lyrics|clip|music)\b'
    r'|\b(?:remaster(?:ed)?(?:\s+\d{4})?)\b'
    r'|\b(?:video\s+(?:lyric|version|oficial))\b'
    r'|\b(?:hd|hq|4k)\b'
    r'|\b(?:actuación\s+tve)\b'
    r'|#\w+'
    r'|🎶|🎵|➤'
    r'|\bmp[34]\b'
    r'|\bshorts?\b'
)

def normalize(s):
    s = s.lower()
    # Strip unicode accents (é→e, ü→u, etc.)
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    s = re.sub(r'\(feat\..*?\)', '', s)
    s = re.sub(r'\[.*?\]', '', s)
    s = _NOISE_RE.sub('', s)
    s = re.sub(r'\b\d{4}\b', '', s)  # strip standalone years
    s = re.sub(r'[^\w\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

# Version / edit labels a provider appends after a dash. Spotify's oEmbed title
# is the TRACK TITLE ALONE, so "I Will Survive - Single Version" is one title,
# not "artist - title". Stripping the tail gives the bare title to compare.
_VERSION_SUFFIX_RE = re.compile(
    r'(?i)\s*[\-–—]\s*(?:'
    r'[^\-–—]*\b(?:version|edit|mix|remix|remaster(?:ed)?|re-?recorded|cut|take|mono|stereo)\b.*'
    r'|from\s+["“].*'          # - From "Saturday Night Fever" Soundtrack
    r'|pt\.?\s*\d+.*'               # - Pt. 1
    r'|[ab]\s+side\b.*'             # - A Side
    r')$'
)

def strip_version_suffix(s):
    stripped = _VERSION_SUFFIX_RE.sub('', s).strip()
    return stripped or s

def titles_match(expected, actual, artist=None):
    e, a = normalize(expected), normalize(actual)
    if not e or not a: return True
    if e == a or e in a or a in e: return True
    # Provider title may carry a version/edit label ("- Single Version").
    a_bare = normalize(strip_version_suffix(actual))
    if a_bare and (e == a_bare or e in a_bare or a_bare in e):
        return True
    if a_bare and SequenceMatcher(None, e, a_bare).ratio() >= 0.75:
        return True
    # Strip artist name from actual title (YouTube often embeds it)
    if artist:
        na = normalize(artist)
        for cand in (a, a_bare):
            if not cand: continue
            c_stripped = re.sub(r'\b' + re.escape(na) + r'\b', '', cand).strip()
            if c_stripped and (e in c_stripped or c_stripped in e):
                return True
            if c_stripped and SequenceMatcher(None, e, c_stripped).ratio() >= 0.75:
                return True
    return SequenceMatcher(None, e, a).ratio() >= 0.75

def wrong_track(expected_title, expected_artist, actual_title, actual_artist=None):
    exp = f"{expected_artist} - {expected_title}"
    act = f"{actual_artist} - {actual_title}" if actual_artist else actual_title
    return {"status": "wrong_track", "http_code": 200,
            "detail": f"Title mismatch: expected '{exp}', got '{act}'",
            "actual_title": actual_title, "actual_artist": actual_artist}

def transient(code, provider):
    return {"status": "error", "http_code": code, "transient": True,
            "detail": f"{provider} throttled/unavailable after {len(RETRY_BACKOFF) + 1} attempts "
                      f"(last HTTP {code}) — not a verdict on the track"}

def check_spotify(tid, title, artist):
    # Spotify's oEmbed "title" is the track title alone — never "Artist - Title".
    # Anything after a dash is a version label, so the raw string goes to
    # titles_match, which strips both the label and an embedded artist name.
    url = f"https://open.spotify.com/oembed?url=spotify:track:{tid}"
    data, code, is_transient = http_json(url, retry_404=True)
    if data is None:
        if is_transient: return transient(code, "Spotify")
        if code == 404: return {"status": "dead", "http_code": 404, "detail": "Not found"}
        if code == 403: return {"status": "dead", "http_code": 403, "detail": "Restricted"}
        return {"status": "unreachable", "http_code": code, "detail": f"Spotify HTTP {code}"}
    actual = data.get("title", "")
    if not titles_match(title, actual, artist):
        return wrong_track(title, artist, actual)
    return {"status": "ok", "http_code": 200}

def check_youtube(tid, title, artist):
    # YouTube titles carry the artist inline in either order ("Queen - Bohemian
    # Rhapsody", "In The End [Official HD Music Video] - Linkin Park"), so the
    # raw title is compared and normalize()/titles_match() do the stripping.
    url = f"https://www.youtube.com/oembed?url=https://music.youtube.com/watch?v={tid}&format=json"
    data, code, is_transient = http_json(url, retry_404=True)
    if data is None:
        if is_transient: return transient(code, "YouTube")
        if code in (404, 401):
            return {"status": "dead", "http_code": code, "detail": "Not found or private"}
        return {"status": "unreachable", "http_code": code, "detail": f"YouTube HTTP {code}"}
    actual = data.get("title", "")
    if not titles_match(title, actual, artist):
        return wrong_track(title, artist, actual, data.get("author_name"))
    return {"status": "ok", "http_code": 200}

def check_deezer(tid, title, artist):
    url = f"https://api.deezer.com/track/{tid}"
    data, code, is_transient = http_json(url)
    if data is None:
        if is_transient: return transient(code, "Deezer")
        return {"status": "unreachable", "http_code": code, "detail": f"Deezer HTTP {code}"}
    if "error" in data:
        return {"status": "dead", "http_code": 200, "detail": data["error"].get("message", "?")}
    actual_title  = data.get("title", "")
    actual_artist = data.get("artist", {}).get("name", "")
    if not titles_match(title, actual_title, artist):
        return wrong_track(title, artist, actual_title, actual_artist)
    return {"status": "ok", "http_code": 200}

def check_tidal(tid, title, artist):
    # Use Tidal's oEmbed API — publicly accessible, no auth required.
    # Same title convention as Spotify: track title, optionally version-suffixed.
    url = f"https://oembed.tidal.com/?url=https://tidal.com/browse/track/{tid}"
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; Beatify-HealthCheck/1.0)"}
    data, code, is_transient = http_json(url, headers=hdrs, retry_404=True)
    if data is None:
        if is_transient: return transient(code, "Tidal")
        if code == 404: return {"status": "dead", "http_code": 404, "detail": "Not found"}
        if code == 403: return _check_tidal_embed(tid, title, artist)
        return {"status": "unreachable", "http_code": code, "detail": f"Tidal HTTP {code}"}
    actual = data.get("title", "")
    if actual and not titles_match(title, actual, artist):
        return wrong_track(title, artist, actual)
    return {"status": "ok", "http_code": 200}

def _check_tidal_embed(tid, title, artist):
    """Fallback for Tidal when oEmbed returns 403 — check the embed page."""
    url = f"https://embed.tidal.com/tracks/{tid}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Beatify-HealthCheck/1.0)"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
            og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og:
                actual_title = og.group(1).strip()
                if not titles_match(title, actual_title, artist):
                    return wrong_track(title, artist, actual_title)
            return {"status": "ok", "http_code": 200}
    except urllib.error.HTTPError as e:
        if e.code == 404: return {"status": "dead", "http_code": e.code, "detail": "Not found"}
        return {"status": "error", "http_code": e.code, "detail": f"Tidal unavailable ({e.code})"}
    except Exception as e: return {"status": "unreachable", "detail": str(e)}

def check_apple_music(tid, title, artist):
    # iTunes Lookup defaults to the US storefront — German-catalog tracks
    # (Karneval, Schlager, etc.) return resultCount=0 there. Try US first,
    # fall back to DE and GB before calling a track dead.
    for country in ("us", "de", "gb"):
        url = f"https://itunes.apple.com/lookup?id={tid}&entity=song&country={country}"
        data, code, is_transient = http_json(url)
        if data is None:
            # iTunes throttles hard (403/429) — never call a track dead on that.
            if is_transient: return transient(code, "Apple Music")
            if code == 404: continue
            return {"status": "unreachable", "http_code": code, "detail": f"iTunes HTTP {code}"}
        if data.get("resultCount", 0) == 0:
            continue
        track = data["results"][0]
        actual_title  = track.get("trackName", "")
        actual_artist = track.get("artistName", "")
        if not titles_match(title, actual_title, artist):
            return wrong_track(title, artist, actual_title, actual_artist)
        return {"status": "ok", "http_code": 200}
    return {"status": "dead", "http_code": 404, "detail": "Not found in US/DE/GB catalogs"}

CHECKERS = {
    "spotify":       check_spotify,
    "youtube_music": check_youtube,
    "deezer":        check_deezer,
    "tidal":         check_tidal,
    "apple_music":   check_apple_music,
}

COOLDOWN = 5.0   # extra pause after a throttled lookup, to let the provider recover

def validate_uris(songs, delay=0.5):
    results = []
    summary = {"total":0,"ok":0,"dead":0,"wrong_track":0,"error":0,"unreachable":0,"unknown":0,
               "transient":0}
    for i, song in enumerate(songs):
        uri, artist, title = song.get("uri",""), song.get("artist",""), song.get("title","")
        summary["total"] += 1
        cooldown = False
        provider, tid = detect_provider(uri)
        if provider == "unknown":
            results.append({"uri":uri,"artist":artist,"title":title,"provider":"unknown",
                            "status":"unknown","detail":f"Unrecognized: {uri}"})
            summary["unknown"] += 1
        elif uri in _DENYLIST:
            entry = _DENYLIST[uri]
            r = {"status": "dead", "http_code": 0,
                 "detail": f"Deny-listed: {entry.get('reason','user-reported failure')} (see {entry.get('source','known_bad_uris.json')})"}
            r.update({"uri":uri,"artist":artist,"title":title,"provider":provider})
            results.append(r)
            summary["dead"] += 1
        else:
            r = CHECKERS[provider](tid, title, artist)
            r.update({"uri":uri,"artist":artist,"title":title,"provider":provider})
            results.append(r)
            summary[r["status"]] = summary.get(r["status"], 0) + 1
            if r.get("transient"):
                summary["transient"] += 1
                cooldown = True
        if i < len(songs) - 1:
            time.sleep(delay + (COOLDOWN if cooldown else 0.0))
        if (i + 1) % 20 == 0:
            print(f"  Checked {i+1}/{len(songs)}...", file=sys.stderr)
    return {"results": results, "summary": summary}

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.json>", file=sys.stderr); sys.exit(1)
    with open(sys.argv[1]) as f: songs = json.load(f)
    print(f"Validating {len(songs)} URIs (with title matching)...", file=sys.stderr)
    report = validate_uris(songs)
    s = report["summary"]
    print(f"Done. {s['ok']} ok, {s['dead']} dead, {s['wrong_track']} wrong track, "
          f"{s.get('error',0)} error, {s.get('unreachable',0)} unreachable.", file=sys.stderr)
    if s.get("transient"):
        # A degraded run must be visible as degraded, not as a wall of defects.
        print(f"  WARNING: {s['transient']} lookup(s) were throttled/unavailable even after "
              f"{len(RETRY_BACKOFF) + 1} attempts — those are provider failures, not track "
              f"defects. Re-run to get a verdict on them.", file=sys.stderr)
    with open(sys.argv[2], "w") as f: json.dump(report, f, indent=2)
    sys.exit(1 if (s["dead"] + s["wrong_track"]) > 0 else 0)
