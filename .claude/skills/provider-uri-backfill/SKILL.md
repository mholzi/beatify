---
name: provider-uri-backfill
description: >
  Recurring backfill job (#1289) that systematically fills missing per-provider
  track URIs across Beatify playlists. For every song that has a Spotify `uri`
  but is missing `uri_apple_music` / `uri_tidal` / `uri_deezer`, it resolves the
  gaps via the keyless Odesli / song.link API (Tidal + Deezer reliably, Apple
  Music best-effort) with a verifying Deezer-ISRC fallback; missing
  `uri_youtube_music` is filled via the YouTube Data API behind a resume-cursor +
  daily quota budget. Rate-limit safe (Odesli throttle + 429 backoff, YouTube
  daily budget). Emits a per-playlist Markdown coverage report. Use this skill
  whenever the user asks to backfill provider URIs, fill missing Apple/Tidal/
  Deezer/YouTube links, improve provider coverage, run the URI backfill, or check
  per-playlist provider coverage.
---

# Provider-URI Backfill

Fills missing per-provider streaming URIs across Beatify playlists so games on
non-Spotify providers (Music Assistant Apple/Tidal/Deezer/YouTube backends) have
something playable for every song. Resolves issue #1289.

## When to use

- Provider coverage drifts after new playlists are added (they ship Spotify-only
  or partial).
- Periodically, to chip away at the Tidal gap (the biggest — ~52% covered) and
  top up Apple/Deezer/YouTube.
- To regenerate the coverage report (`docs/provider-coverage.md`).

## How to run

The script defaults to **dry-run** (writes only the coverage report; never
touches playlist JSON). Gate real writes behind `--apply`.

```bash
# Dry-run: coverage report only (safe, no JSON mutation). No keys needed for
# the report itself; Odesli is hit only for fillable songs.
python3 .claude/skills/provider-uri-backfill/scripts/backfill_provider_uris.py \
  --repo-root . --playlist eurovision-winners

# Apply: write resolved URIs back to JSON.
python3 .claude/skills/provider-uri-backfill/scripts/backfill_provider_uris.py \
  --repo-root . --playlist eurovision-winners --apply
```

Run one playlist at a time (`--playlist <basename>` or `--playlist community/<name>`)
to keep within Odesli's free rate limit. Without `--playlist` it walks the whole
catalog (main + community) — expect this to take a long time because of the
6 s/track Odesli throttle.

### Options

| Flag | Default | Purpose |
|---|---|---|
| `--repo-root` | `.` | Beatify repo root |
| `--playlist` | all | Process one playlist (basename or `community/<name>`) |
| `--apply` | off | Write filled URIs back to JSON + bump each modified playlist's `version` (minor +1); else dry-run report only |
| `--output` | `docs/provider-coverage.md` | Coverage report path |
| `--state` | `skill/.backfill-state.json` | YouTube resume-cursor + daily-budget state |
| `--odesli-sleep` | `6.0` | Seconds between Odesli calls (free tier ~10/min) |
| `--youtube-budget` | `90` | Max YouTube `search.list` calls per day |

## Resolvers + stored URI formats

The script writes **byte-identical** stored formats (verified against existing
non-null values + a live Odesli probe, 2026-06):

| Field | Stored format | Source |
|---|---|---|
| `uri_tidal` | `tidal://track/<numeric>` | Odesli `entityUniqueId` `TIDAL_SONG::<id>` (or URL `/track/<id>`) |
| `uri_deezer` | `deezer://track/<numeric>` | Odesli `DEEZER_SONG::<id>`; fallback `api.deezer.com/track/isrc:<ISRC>` |
| `uri_apple_music` | `applemusic://track/<numeric>` | Odesli `appleMusic`/`itunes` entity id, **when present** (often absent — see below) |
| `uri_youtube_music` | `https://music.youtube.com/watch?v=<11-char-id>` | YouTube Data API `search.list` top hit |

If the script cannot confidently extract a numeric id in the expected format for
a provider, it **skips** that provider for that song (it never guesses a format).

### Odesli / song.link (primary)

One `GET https://api.song.link/v1-alpha.1/links?url=<spotify-url>` per track maps
the Spotify URI to all providers at once. Keyless, free, ~10 req/min — the script
sleeps `--odesli-sleep` (6 s) between calls and retries HTTP 429 with exponential
backoff. If the backoff is exhausted (or any other Odesli error), the track is
**skipped** for this wave (never raised — that would abort the run and lose
partial progress); the next wave retries it. Under `--apply` progress is flushed
to disk after every resolved song, so a mid-run 429 wall keeps everything already
written, and the independent YouTube phase runs regardless of Odesli's state.

**Known limitation:** Odesli's keyless responses frequently omit Apple Music
entirely (observed live for multiple mainstream tracks, 2026-06). Tidal + Deezer
come back reliably. Apple gaps are therefore better served by the existing
[`playlist-health-check` Mode 2](../playlist-health-check/SKILL.md) (Apple Music
API + per-region ISRC), with this skill catching whatever Odesli happens to
surface. Deezer has a secondary ISRC verify (`api.deezer.com/track/isrc:<ISRC>`)
when Odesli misses it.

### YouTube Data API (YouTube only)

Odesli's `youtube` field is unreliable for this catalog, so `uri_youtube_music`
uses `search.list` (100 quota units each; 10,000/day default ⇒ ~100 searches/day).
A **resume cursor** + **daily budget** in `.backfill-state.json` cap each run at
`--youtube-budget` searches and resume the catalog scan across days/runs:

```json
{"youtube": {"date": "2026-06-10", "spent_today": 90, "cursor": 512, "budget": 90}}
```

`spent_today` resets when the date rolls over; `cursor` carries forward so the
next day continues where the last left off. The key is read from `YOUTUBE_API_KEY`;
if unset the whole YouTube phase is **skipped gracefully** with a note in the
report (no crash). Never hardcode a key.

## Coverage report

`docs/provider-coverage.md` (style like `docs/beatify-stats.md`): a summary table
of per-provider coverage across the whole catalog plus a per-playlist table
showing how many songs have Apple/Tidal/Deezer/YouTube vs total, and how many URIs
this run filled (0 in dry-run).

## Scope / safety

- **Dry-run by default.** `--apply` is required to mutate JSON. A mass backfill of
  2000+ files is a deliberate follow-up, not a side effect of running the report.
- Touches only `custom_components/beatify/playlists/**` JSON and the report — no
  `www/**`, no schema changes. There is no `uri_amazon_music` field, so Amazon is
  out of scope despite Odesli returning it.
- iTunes Search is intentionally NOT used (ban risk); Apple gaps go through the
  health-check Mode 2 flow.

## Tests

Pure logic (Odesli→URI mapping per provider, gap detection, resume-cursor
accounting, coverage aggregation) is unit-tested with mocked HTTP in
`tests/unit/test_provider_uri_backfill.py` — no network in tests.
