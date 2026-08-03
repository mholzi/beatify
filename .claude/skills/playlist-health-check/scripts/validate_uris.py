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
    # Fold compatibility forms first: Japanese catalogues mix fullwidth and
    # halfwidth latin, so "少女Ｓ" and "少女S" are the same title written two
    # ways. NFKC maps Ｓ→S, ﬁ→fi, ①→1 — none of which changes meaning.
    s = unicodedata.normalize('NFKC', s).lower()
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

# YouTube auto-generates an "<Artist> - Topic" channel per artist, and labels
# publish under "<Artist>VEVO". Neither is part of the artist's name.
_CHANNEL_SUFFIX_RE = re.compile(r'(?i)(?:\s*[\-–—]\s*topic|\s*vevo)\s*$')

def strip_channel_suffix(s):
    stripped = _CHANNEL_SUFFIX_RE.sub('', s or '').strip()
    return stripped or s

# Codepoint blocks that carry no Latin transliteration: a title written in one
# of these cannot be string-compared against a romanised or translated title.
_CJK_RE = re.compile(
    r'[぀-ゟ'   # Hiragana
    r'゠-ヿ'    # Katakana
    r'㐀-䶿'    # CJK Ext A
    r'一-鿿'    # CJK Unified
    r'가-힯'    # Hangul
    r'ｦ-ﾟ]'   # Halfwidth Katakana
)

def has_cjk(s):
    return bool(_CJK_RE.search(s or ''))

def scripts_differ(expected, actual):
    """True when exactly one side is written in a non-Latin script.

    Providers legitimately return Japanese tracks romanised ("紅蓮華" →
    "Gurenge") or translated ("百花繚乱" → "In Bloom"). A string comparison
    across that boundary answers nothing — it always says "mismatch", which is
    why anime-openings produced 308 flags and 0 real defects (#1957).
    """
    return has_cjk(expected) != has_cjk(actual)

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

def title_verdict(expected, actual, artist=None):
    """'match' | 'unverifiable' | 'mismatch'.

    'unverifiable' means the two titles are written in different scripts, so
    the comparison cannot decide the question either way. The URI resolved and
    the track exists — it is simply not checkable by string equality, and is
    reported as its own status rather than as a defect.
    """
    if titles_match(expected, actual, artist):
        return "match"
    if scripts_differ(expected, actual):
        return "unverifiable"
    return "mismatch"

def unverifiable_title(expected_title, actual_title, actual_artist=None):
    actual_artist = strip_channel_suffix(actual_artist) if actual_artist else None
    return {"status": "unverifiable", "http_code": 200,
            "detail": f"Title written in a different script — expected "
                      f"'{expected_title}', got '{actual_title}'. Not comparable "
                      f"by string match; no verdict.",
            "actual_title": actual_title, "actual_artist": actual_artist}

def wrong_track(expected_title, expected_artist, actual_title, actual_artist=None):
    actual_artist = strip_channel_suffix(actual_artist) if actual_artist else None
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
    v = title_verdict(title, actual, artist)
    if v == "mismatch":
        return wrong_track(title, artist, actual)
    if v == "unverifiable":
        return unverifiable_title(title, actual)
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
    v = title_verdict(title, actual, artist)
    if v == "mismatch":
        return wrong_track(title, artist, actual, data.get("author_name"))
    if v == "unverifiable":
        return unverifiable_title(title, actual, data.get("author_name"))
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
    v = title_verdict(title, actual_title, artist)
    if v == "mismatch":
        return wrong_track(title, artist, actual_title, actual_artist)
    if v == "unverifiable":
        return unverifiable_title(title, actual_title, actual_artist)
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
    if actual:
        v = title_verdict(title, actual, artist)
        if v == "mismatch":
            return wrong_track(title, artist, actual)
        if v == "unverifiable":
            return unverifiable_title(title, actual)
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
                v = title_verdict(title, actual_title, artist)
                if v == "mismatch":
                    return wrong_track(title, artist, actual_title)
                if v == "unverifiable":
                    return unverifiable_title(title, actual_title)
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
        v = title_verdict(title, actual_title, artist)
        if v == "mismatch":
            return wrong_track(title, artist, actual_title, actual_artist)
        if v == "unverifiable":
            return unverifiable_title(title, actual_title, actual_artist)
        return {"status": "ok", "http_code": 200}
    return {"status": "dead", "http_code": 404, "detail": "Not found in US/DE/GB catalogs"}

CHECKERS = {
    "spotify":       check_spotify,
    "youtube_music": check_youtube,
    "deezer":        check_deezer,
    "tidal":         check_tidal,
    "apple_music":   check_apple_music,
}

# ---------------------------------------------------------------------------
# Region-map validation (uri_apple_music_by_region)
#
# check_apple_music above validates the *base* field only, and it accepts a
# track as healthy as soon as the id resolves in ANY of us/de/gb. Both
# properties hide a real class of defect:
#
#   * 36% of tracks carry a by-region map whose ids differ from the base
#     field entirely, so the base check never touches them. Aerosmith
#     "Dream On" had a valid base id while its map pointed at 1885596530,
#     dead in all nine storefronts checked — and the daily run reported the
#     playlist as healthy.
#   * A track present in DE but absent in US/GB passes the base check, so a
#     map claiming us/gb was never contradicted.
#
# This pass resolves every *claimed* region separately. Regions whose map
# entry is null are not defects — they are simply unfilled (Mode 2 never ran
# for that track) and are counted apart.
#
# Cost is kept low by batching: iTunes' lookup endpoint accepts up to ~40
# comma-separated ids per call, so a 100-track playlist across 7 regions is
# ~21 requests rather than 700 sequential ones — cheaper than the per-track
# pass it complements.
# ---------------------------------------------------------------------------

REGION_BATCH = 40
REGION_DELAY = 1.0


def _lookup_batch(ids, country):
    """Resolve a batch of Apple track ids in one storefront.

    Returns (found_map, transient). ``found_map`` maps id -> track dict for
    everything the storefront knows. ``transient`` is True when the lookup
    itself failed (throttled/unreachable) — the caller must then not treat
    any id in the batch as dead.
    """
    url = ("https://itunes.apple.com/lookup?id=" + ",".join(ids)
           + f"&entity=song&country={country}")
    data, code, is_transient = http_json(url, timeout=25)
    if data is None:
        return {}, True if (is_transient or code is None) else False
    found = {}
    for t in data.get("results", []):
        tid = t.get("trackId")
        if tid is not None:
            found[str(tid)] = t
    return found, False


def validate_region_maps(entries):
    """Validate uri_apple_music_by_region entries.

    ``entries`` is a list of dicts:
        {"artist", "title", "regions": {"us": "applemusic://track/123", ...}}

    Returns {"results": [...], "summary": {...}} where each result is one
    (track, region) pair that was actually claimed.
    """
    results = []
    summary = {"total": 0, "ok": 0, "dead": 0, "wrong_track": 0,
               "unverifiable": 0, "unfilled": 0, "transient": 0, "tracks_affected": 0}

    # Collect claimed (region -> [(id, entry)]) so each storefront is queried
    # in as few calls as possible.
    by_region = {}
    for e in entries:
        regions = e.get("regions") or {}
        for country, uri in regions.items():
            if not uri:
                summary["unfilled"] += 1
                continue
            provider, tid = detect_provider(uri)
            if provider != "apple_music":
                results.append({"artist": e.get("artist"), "title": e.get("title"),
                                "region": country, "uri": uri, "provider": "apple_music",
                                "status": "unknown",
                                "detail": f"Not an Apple Music URI: {uri}"})
                summary["total"] += 1
                summary["unknown"] = summary.get("unknown", 0) + 1
                continue
            by_region.setdefault(country, []).append((tid, e))
            summary["total"] += 1

    affected = set()
    for country in sorted(by_region):
        pairs = by_region[country]
        for i in range(0, len(pairs), REGION_BATCH):
            chunk = pairs[i:i + REGION_BATCH]
            found, transient = _lookup_batch([tid for tid, _ in chunk], country)
            for tid, e in chunk:
                base = {"artist": e.get("artist"), "title": e.get("title"),
                        "region": country, "uri": f"applemusic://track/{tid}",
                        "provider": "apple_music"}
                if transient:
                    base.update({"status": "unreachable", "transient": True,
                                 "detail": f"iTunes lookup for storefront {country} "
                                           f"failed after retries — no verdict"})
                    summary["transient"] += 1
                    results.append(base)
                    continue
                track = found.get(tid)
                if track is None:
                    base.update({"status": "dead", "http_code": 404,
                                 "detail": f"Claimed for storefront {country}, "
                                           f"but not in that catalog"})
                    summary["dead"] += 1
                    affected.add((e.get("artist"), e.get("title")))
                elif (v := title_verdict(e.get("title", ""), track.get("trackName", ""),
                                         e.get("artist", ""))) == "mismatch":
                    r = wrong_track(e.get("title", ""), e.get("artist", ""),
                                    track.get("trackName", ""), track.get("artistName", ""))
                    base.update(r)
                    base["detail"] = f"[{country}] " + base.get("detail", "")
                    summary["wrong_track"] += 1
                    affected.add((e.get("artist"), e.get("title")))
                elif v == "unverifiable":
                    # Apple Music localises titles per storefront, so a German
                    # storefront returns "Inferno" where the catalogue says
                    # "インフェルノ". Not a defect and not an affected track.
                    base.update(unverifiable_title(e.get("title", ""),
                                                   track.get("trackName", ""),
                                                   track.get("artistName", "")))
                    base["detail"] = f"[{country}] " + base.get("detail", "")
                    summary["unverifiable"] = summary.get("unverifiable", 0) + 1
                else:
                    base.update({"status": "ok", "http_code": 200})
                    summary["ok"] += 1
                results.append(base)
            time.sleep(REGION_DELAY)

    summary["tracks_affected"] = len(affected)
    return {"results": results, "summary": summary}

COOLDOWN = 5.0   # extra pause after a throttled lookup, to let the provider recover

def validate_uris(songs, delay=0.5):
    results = []
    summary = {"total":0,"ok":0,"dead":0,"wrong_track":0,"unverifiable":0,"error":0,
               "unreachable":0,"unknown":0,"transient":0}
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
    with open(sys.argv[1]) as f: payload = json.load(f)

    # Input is either the historical flat list of URI entries, or an object
    # that additionally carries region maps. Both are accepted so an older
    # runner keeps working against a newer validator.
    if isinstance(payload, dict):
        songs = payload.get("uris", [])
        region_entries = payload.get("region_maps", [])
    else:
        songs, region_entries = payload, []

    print(f"Validating {len(songs)} URIs (with title matching)...", file=sys.stderr)
    report = validate_uris(songs)
    s = report["summary"]
    print(f"Done. {s['ok']} ok, {s['dead']} dead, {s['wrong_track']} wrong track, "
          f"{s.get('unverifiable',0)} unverifiable (different script), "
          f"{s.get('error',0)} error, {s.get('unreachable',0)} unreachable.", file=sys.stderr)
    if s.get("transient"):
        # A degraded run must be visible as degraded, not as a wall of defects.
        print(f"  WARNING: {s['transient']} lookup(s) were throttled/unavailable even after "
              f"{len(RETRY_BACKOFF) + 1} attempts — those are provider failures, not track "
              f"defects. Re-run to get a verdict on them.", file=sys.stderr)

    rs = {}
    if region_entries:
        claimed = sum(1 for e in region_entries
                      for v in (e.get("regions") or {}).values() if v)
        print(f"Validating {claimed} claimed region(s) across {len(region_entries)} "
              f"track(s) (batched)...", file=sys.stderr)
        region_report = validate_region_maps(region_entries)
        report["region_results"] = region_report["results"]
        report["region_summary"] = rs = region_report["summary"]
        print(f"Region maps: {rs['ok']} ok, {rs['dead']} dead, "
              f"{rs['wrong_track']} wrong track, "
              f"{rs.get('unverifiable',0)} unverifiable (different script), "
              f"{rs['unfilled']} unfilled "
              f"({rs['tracks_affected']} track(s) affected).", file=sys.stderr)
        if rs.get("transient"):
            print(f"  WARNING: {rs['transient']} region lookup(s) had no verdict "
                  f"(throttled/unreachable) — re-run before acting on them.",
                  file=sys.stderr)

    with open(sys.argv[2], "w") as f: json.dump(report, f, indent=2)
    # Region defects count toward the failure exit code as well — a dead id in
    # a region map breaks playback for users in that region just as surely as a
    # dead base URI does.
    defects = (s["dead"] + s["wrong_track"]
               + rs.get("dead", 0) + rs.get("wrong_track", 0))
    sys.exit(1 if defects > 0 else 0)
