# Beatify "Crate Digger" Mode — Technical Reference & Handoff

**Version documented:** 0.8.0 (engine by DMW)
**Upstream base:** `mholzi/beatify` **4.2.0** (stable, rebased onto the release tag)
**Status:** rebased onto 4.2.0 and green on upstream's own suites (1623 + 584 tests, build:check clean); pending a hardware pass on the rebased build
**Scope of this document:** everything a new maintainer (or mholzi) needs in order to continue this work without reverse-engineering anything

---

## 0. How to read this document

This reference is organised so you can enter at whatever depth you need:

| If you want to… | Read |
|---|---|
| Understand what this is and why it exists | §1 |
| Get it running and start editing today | §2 |
| Understand the data pipeline end-to-end | §3 |
| Work inside the new engine code | §4, §5 |
| Call or extend the HTTP API | §6 |
| Know exactly what was changed in upstream files | §7, §8 |
| Understand *why* a design is the way it is | §9 |
| Understand a workaround that looks strange | §10, §11 |
| Ship a release safely | §12 |
| Merge this into upstream Beatify | §13 |
| Know what is still open | §14 |
| Debug a live system | §15 |

Two conventions used throughout:

* **"Upstream"** means unmodified `mholzi/beatify` code.
* **"Ours"** means code added or changed by this work. The mode is called
**Crate Digger**; the internal provider id remains `ma_library`, so renaming the
mode is a string change rather than a refactor.

Every non-obvious workaround in the codebase carries an inline comment explaining the failure it prevents. Those comments are load-bearing documentation — **please do not strip them during a rebase.** Several of them describe bugs that took multiple release cycles to find, and their removal is how the bugs come back.

---

## 1. Executive summary

### 1.1 What this is

A **library game provider** for Beatify. Instead of streaming songs from Spotify/Apple/YouTube/Tidal/Deezer, a game is sampled from **the host's own music library** (Plex, Jellyfin, local files — anything Music Assistant exposes as a library provider) and played back through Music Assistant.

It addresses upstream issue **#45** (Plex support), which had been abandoned as impractical. The practicality problem was never playback — Music Assistant can already play a library track. The problem is **metadata quality**:

* A guessing game about release years is only fair if the **year is correct**. Local file tags are frequently wrong; compilation and "greatest hits" rips carry the *pressing* year, not the *recording* year — a 1965 song tagged 1998.
* A difficulty slider is only meaningful if "famous" means **famous in the world**, not "famous inside this particular library". A deep cut in a Top-40 collection and a deep cut in a jazz collection must be judged by the same yardstick.
* Genre filtering is only useful if genres exist. Music Assistant's *list* models return no genres at all (measured: 20 000 list fetches → 0 genres).

This provider solves all three by building an **enriched, cached pool** of the user's library, with MusicBrainz-verified years, worldwide popularity scores from Deezer, and genres assembled from several sources. Games are then sampled from that pool.

### 1.2 Design constraints that shaped everything

1. **No new hard dependencies.** Everything uses `aiohttp` via HA's shared session. No extra Python packages, no build step for the backend.
2. **Nothing may degrade the existing providers.** The provider is additive; all upstream code paths must behave identically when the provider isn't selected.
3. **The pool is built once, then reused.** Enrichment costs external API calls (MusicBrainz is rate-limited to ~1 req/s); a 295 000-track library cannot be enriched at game start. The pool is a durable, incrementally-extendable cache.
4. **Fairness over convenience.** Where a choice existed between "more songs available" and "more trustworthy songs", trustworthiness won. This is why the default year gate is *external-primary only*.
5. **The server is the source of truth.** Learned the hard way (§10.2): any setting that lives only in the browser will eventually be applied to the wrong game.

### 1.3 What works today (hardware-verified)

* Library scanning and incremental enrichment (author's pool: ~51 000 of ~295 000 tracks scanned)
* Year verification via MusicBrainz with a confidence ladder and compilation detection
* Worldwide popularity via Deezer, normalised to a 0–100 fame scale plus in-pool percentiles
* Genre assembly (MA detail fetches → MusicBrainz tags → Deezer album genres) with a genre-adjacency fallback
* A "Top P% of my library" popularity control, genre chips, size, and year-strictness gate — all server-shared
* Full game integration: lobby, rounds, reveal, scoring, rematch, all output settings
* Playback through Music Assistant, including voice satellites, Android TV (ShieldTV), Echo devices and tablets
* TTS announcements with an automatic resume watchdog for devices that fail to resume
* Party lights, TTS, and output-device changes applied to the game being started (not the next one)

---

## 2. Quick start for a new maintainer

### 2.1 Installing a build

The release artifact is a zip containing a complete `custom_components/beatify` tree plus tooling:

```bash
cd /config/custom_components
rm -rf _new && mkdir _new
unzip -q beatify-my-library-v0.7.23.zip -d _new
rm -rf beatify
mv _new/beatify-my-library/custom_components/beatify beatify
rm -rf _new
ha core check && ha core restart
```

If the frontend changed, do **one hard refresh** of the admin page (the service worker cache suffix is bumped every frontend release; currently `-mylib17`).

### 2.2 Repository layout

```
custom_components/beatify/
├── library/                    ← NEW: the entire provider engine (ours, ~3 500 LOC)
│   ├── __init__.py             ← public entry point: async_generate_library_playlist
│   ├── ma_client.py            ← Music Assistant access (tracks, genres, URI resolution)
│   ├── year_resolver.py        ← MusicBrainz + confidence ladder + compilation detection
│   ├── popularity.py           ← Deezer/Last.fm ranks → 0-100 fame score, percentiles, bands
│   ├── pool.py                 ← scan/enrich/persist/refresh the cached pool
│   ├── generator.py            ← sampling: gates, windows, genre adjacency, decade balance
│   ├── matcher.py              ← pool indexing + AI-curation resolution helpers
│   ├── backup.py               ← bundle assembly, validation, pool merging (pure)
│   └── version.py              ← provider version + the full annotated changelog
├── server/
│   ├── library_views.py        ← NEW: all library HTTP endpoints + settings stores
│   └── game_views.py           ← MODIFIED: library game creation, pre-start hook, UpdateLobbyView
├── game/
│   ├── state_lifecycle.py      ← MODIFIED: pre-start hook firing, TTS resume watchdog
│   ├── state_setup.py          ← MODIFIED: replace_songs(), create-time service resets
│   ├── playlist.py             ← MODIFIED: ma_library URI branch
│   └── serializers.py          ← MODIFIED: server_now_ms clock stamp
├── services/
│   └── media_player.py         ← MODIFIED: ma_library playback, enqueue=replace, volume re-assert
├── www/                        ← MODIFIED: admin panel, wizard step, CSS, i18n, service worker
├── const.py                    ← MODIFIED: PROVIDER_MA_LIBRARY, URI_PATTERN_MA_LIBRARY
└── __init__.py                 ← MODIFIED: view registration, build_library_pool service
tools/check_imports.py          ← static intra-package import verification
tests/test_smoke.py             ← 25 runtime + source guards (one per shipped bug class)
tests/test_generator_related.py ← 9 pure logic checks for genre adjacency
```

### 2.3 The development loop

```bash
# 1. edit Python
find custom_components -name "*.py" -exec python3 -m py_compile {} +   # syntax
python3 tools/check_imports.py                                        # import graph
python3 tests/test_smoke.py                                           # bug-class guards
python3 tests/test_generator_related.py                               # pure logic

# 2. if JS/CSS changed, rebuild the bundles (the page loads the .min files)
cd custom_components/beatify/www
npx -y esbuild js/admin.js --bundle --minify --format=esm --outfile=js/admin.min.js
npx -y esbuild css/library.css --minify --sourcemap --outfile=css/library.min.css
# then bump the cache suffix in sw.js (…-mylib17 → -mylib18)

# 3. bump version + changelog in library/version.py, package, verify contents, ship
```

**The gate must be green before packaging, not after.** This has caught real boot-blockers, including one introduced by the very fix it was gating (§12.2).

### 2.4 Where things live at runtime

| Thing | Location |
|---|---|
| Enriched pool | `/config/beatify/library_pool.json` |
| Library game settings | HA Store `beatify.library_settings` |
| Output settings (device/TTS/lights) | HA Store `beatify.game_output_settings` |
| Last-generation summary | `hass.data[DOMAIN]["library_last_generate"]` |
| Recently-played URIs | `hass.data[DOMAIN]` (rolling window, see §5.4) |

---

## 3. System architecture

### 3.1 The five stages

```
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 1. ENUMERATE          ma_client.async_iter_all_library_tracks        │
   │    Music Assistant  → title, artist, album, uri, provider, item_id   │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │  (LAN-local, paginated, no rate limit)
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ 2. ENRICH             pool.async_build_pool                          │
   │    ├── genres:    MA detail fetch → MusicBrainz tags → Deezer album  │
   │    ├── year:      year_resolver.resolve_year (MusicBrainz primary)   │
   │    └── fame:      popularity.async_deezer_rank_album → score 0-100   │
   │    Checkpointed every 200 songs (crash-safe, resumable, additive)    │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ 3. PERSIST            pool.finalize_pool → library_pool.json         │
   │    Adds in-pool percentiles + familiarity bands over global_score    │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ 4. SAMPLE             generator.generate_playlist                    │
   │    trust gate → dedupe → genre filter → recency exclusion            │
   │    → popularity window → related-genre fill → widening → unknown     │
   │    → decade balancing → Beatify song dicts                           │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ 5. PLAY               services/media_player.py                       │
   │    music_assistant.play_media(media_id=uri, enqueue=replace)         │
   │    + name-fallback resolution, volume re-assert, TTS resume watchdog │
   └──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Two independent lifecycles

It is important to keep these apart when reasoning about bugs:

**The pool lifecycle** is slow, external, and user-triggered. Scans take hours; they are incremental and resumable; nothing about a game touches them.

**The game lifecycle** is fast and local. It reads the pool from disk, samples 30 songs in ~300 ms, and hands them to upstream's `PlaylistManager`. Every bug in §10.1 and §10.2 lived in the *seam* between the game lifecycle and the settings that are supposed to feed it.

### 3.3 The critical seam: when settings are applied

Upstream Beatify **freezes a game's parameters at room creation**. This is a perfectly reasonable design when a room is created immediately before it is played. It becomes a trap when the UI allows settings to change while a room already exists — which it does, because the lobby's reset button creates the next room *instantly*.

Our architecture therefore establishes a second application point:

```
  create_game(…)                     ← upstream: parameters frozen here
       │
       ├─ songs sampled with settings at creation time
       ├─ game_state.pre_start_hook = _regen_library_songs   ← ours (injected)
       │
  … user changes settings in the panel …
       │
       ├─ POST /beatify/api/game/update-lobby                ← ours (applies now + persists)
       │
  start_round()  (first round only, phase LOBBY)
       │
       └─ pre_start_hook fires                               ← ours
            ├─ re-sample songs from CURRENT stored settings
            └─ re-apply device / TTS / party lights from the Store
```

The hook fires from **`start_round()`**, not from the REST view, and that placement is deliberate: the websocket admin handler calls `start_round()` directly and bypasses the REST view entirely. Hooking the view fixed the bug for one path and left it alive on the other — see §10.1.

---

## 4. The `library/` package, module by module

All of this code is new. It has no dependency on Beatify's game logic and can be unit-tested standalone (only `homeassistant.core.HomeAssistant` is imported, and only for typing).

### 4.1 `ma_client.py` — Music Assistant access

Music Assistant's Python client is reached through its config entry's runtime data. There is no stable public API for this, so the module is defensive: it locates entries via `find_ma_config_entry_ids()`, and every model access goes through `_normalize_track()`, which tolerates both object and dict shapes across MA versions.

Key functions:

| Function | Purpose |
|---|---|
| `async_iter_all_library_tracks(hass, entry_id, …)` | Paginated enumeration of the entire library |
| `async_probe_library_total(hass, entry_id)` | Cheap total-count probe (drives the UI's progress) |
| `async_sample_new_tracks(…)` | Fetch a subset for additive scans |
| `async_fetch_track_genres(hass, jobs, …)` | **Detail** fetches, concurrent, failure-tolerant |
| `async_resolve_uri_by_name(hass, title, artist)` | Name→URI fallback when a stored URI goes stale |
| `split_library_uri(uri)` | `provider--instance://track/id` → `(provider, item_id)` |

**Why detail fetches for genres:** MA's list models are slim. A 16 000-track list enumeration produced **zero** genres. Genres only appear on the per-item detail model, so the pool builder issues a detail fetch per new track. These are LAN-local and cheap, executed concurrently, and any individual failure is swallowed (a missing genre is not worth failing a scan over).

**URI volatility:** library URIs are only valid for the MA server that produced them. That is why `const.URI_PATTERN_MA_LIBRARY` is permissive and why playback has a name-based fallback (§7.5). If a user rebuilds their Plex library, URIs can change; the fallback keeps games playable without a rescan.

### 4.2 `year_resolver.py` — the trust ladder

The heart of the fairness guarantee. A song's year is only as good as its source, so every year carries a **confidence**:

```python
class YearConfidence(IntEnum):
    NONE = 0
    TAG_COMPILATION = 1   # tag year from a comp/live/soundtrack → pressing year
    TAG_STUDIO = 2        # tag year from a studio album/single by the real artist
    EXTERNAL_SECONDARY = 3 # a second external source (e.g. Deezer release year)
    EXTERNAL_PRIMARY = 4   # MusicBrainz, match-quality-verified → authoritative

DEFAULT_MIN_CONFIDENCE = int(YearConfidence.EXTERNAL_PRIMARY)
```

The default gate is **EXTERNAL_PRIMARY only**. Everything below it exists so a user with poor external coverage can deliberately relax the gate, not because we consider tag years acceptable.

Three mechanisms make the resolver work on messy libraries:

**Compilation detection.** `_looks_like_compilation()` combines album *type* (`compilation`, `soundtrack`, `live`), "Various Artists" markers, and a name regex covering the usual suspects (Greatest Hits, Now That's What I Call…, Best Of, etc.). A hit demotes a tag year to `TAG_COMPILATION`, because that year is the *pressing* date. This is the single biggest source of wrong years in real libraries.

**Title query candidates.** MusicBrainz matches badly on decorated titles. `title_query_candidates()` generates progressively cleaner queries: the raw title, a version-suffix-stripped form (`(Remastered 2011)`, `- Radio Edit`, `[Live]`…), and — added in v0.7.3 as `_RESOLVER_V = 3` — **the right-hand side of a dash**. That last one exists because of tracks like `Main Title - Scarface`, where the actual work name follows the dash; without it, an entire class of soundtrack and classical tracks resolved to nothing.

**Match verification.** A MusicBrainz result is only accepted if artist and title actually correspond (normalised comparison). An unverified high-scoring result is discarded rather than trusted — a wrong authoritative year is worse than no year, because it silently poisons games.

MusicBrainz is called with a proper `User-Agent` identifying the integration, and is rate-limited to respect their service policy. This politeness is not optional; MusicBrainz will block a badly-behaved client and every user of this provider shares the same UA.

### 4.3 `popularity.py` — worldwide fame, not local fame

Raw popularity signals differ per source, so everything is normalised onto a **0–100 global fame scale** by `to_global_score()`:

* **Deezer rank** (primary): `log10(rank) / _DEEZER_LOG_CEILING * 100`. Log scaling matters — raw ranks are wildly skewed, and a linear mapping puts everything except megahits in the bottom few points.
* **Last.fm listeners** (optional, needs a user-supplied API key): same log treatment against its own ceiling.
* **0–100 sources**: clamped through.

Deezer results are verified before being trusted (`deezer_result_matches()`), because a fuzzy search hit on a different artist would assign a stranger's fame to your track.

Two derived quantities:

* **`global_score`** — absolute worldwide fame. Comparable across libraries.
* **`popularity_percentile`** — rank *within this pool*, computed by `assign_percentiles()` with standard fractional ranking (ties share the average). Songs without a score stay `None` — deliberately "unknown", never falsely "obscure".

Both are needed, and §9.3 explains the hybrid that uses them together.

### 4.4 `pool.py` — build, checkpoint, refresh

The most operationally demanding module: it runs for hours against a live HA instance.

**Additive scanning.** `select_scan_subset()` picks what to scan; already-cached tracks are *not* re-enriched. They get their cheap fields refreshed in memory (title/artist/album/genres) and are skipped. This fixed a real bug where a "1 000-song scan" reported 16 000 because cached entries were being counted and iterated again.

**Checkpointing.** The pool is written every `_CHECKPOINT_BATCH = 200` enriched songs. An HA restart mid-scan costs at most 200 songs of work.

**Versioned re-check flags.** `genres_checked` is an *int* version (`_GENRES_CHECK_V = 2`), with legacy `True` treated as v1. This lets a later release re-check genres for entries checked by an older, worse algorithm without forcing a full rescan. Use the same pattern for any future enrichment step.

**`finalize_pool()` is module-level, deliberately.** Both the build and refresh paths call it. It was originally a closure inside the build function, and the refresh path crashed twice on names that only existed inside that closure (`_CHECKPOINT_BATCH`, then the function itself). Extracting it ended that class of bug. **Do not re-nest shared helpers.**

The persisted pool:

```jsonc
{
  "_schema": <int>,            // pool schema version
  "_engine_version": "…",      // provider version that wrote it
  "_built_at": <epoch>,
  "_config_entry_id": "…",     // which MA server produced these URIs
  "_track_count": <int>,
  "_library_total": <int>,     // MA's reported library size (for progress %)
  "_target_size": <int>,
  "_usable_count": <int>,      // songs meeting DEFAULT_MIN_CONFIDENCE
  "songs": [ … ]
}
```

A pool entry:

```jsonc
{
  "title": "…", "artist": "…", "album": "…",
  "uri_ma_library": "plex--<id>://track/<key>",
  "genres": ["Rock", "Classic Rock"],
  "genres_checked": 2,
  "year": 1982,
  "year_confidence": 4,              // YearConfidence
  "year_source": "musicbrainz",
  "global_score": 71.4,              // 0-100 worldwide fame
  "popularity_percentile": 0.982,    // rank within this pool
  "familiarity_band": "mainstream"   // derived from the percentile
}
```

### 4.5 `generator.py` — the sampling pipeline

Pure, synchronous, fully unit-testable, accepts an injectable `rng` for determinism. The stages, in order:

1. **Trust gate** — drop anything without a year, below `min_confidence`, or without a library URI.
2. **Dedupe** by normalised `(artist, title)`, keeping the higher-confidence copy. Libraries are full of the same song on five albums.
3. **Genre filter** (any-match, case-insensitive). A pre-filter snapshot `pre_genre_deduped` is retained for the adjacency fallback.
4. **Recency exclusion** — drop URIs played in recent games, but **only if enough songs remain** to fill the game. Repeat-avoidance must never make a game impossible.
5. **Popularity window** — `[lo, hi]` percentile window from "Top P%".
   * **Hybrid absolute floor:** for narrow windows (`lo >= 0.5`) an absolute `global_score` floor of `40 + 30·lo` is also required. Rationale in §9.3.
6. **Related-genre fill** (§9.4) — if short, take same-window songs from *adjacent* genres.
7. **Graceful widening** — if still short, rank the scored pool by percentile and take the top `size`. "Top 5% Jazz" degrades to "the most popular Jazz you own", never to random obscurities.
8. **Unknown-popularity fill** — last resort, and only when the window already reaches into the obscure end (`hi >= 0.66`).
9. **Decade balancing** — flattens the decade distribution so a library heavy in one era doesn't produce a one-decade game.

Diagnostics are returned alongside the songs and surfaced in both the log and the panel: `_eligible_count`, `_window_widened`, `_genres_expanded`.

### 4.6 `matcher.py` — indexing for curation

Small module supporting the AI-curation feature: `build_pool_index()` and `build_export_index()` produce compact artist/title indexes suitable for pasting into an LLM, and `resolve_picks()` maps returned picks back to pool entries (normalised matching, tolerant of punctuation and case). This is how a user can ask an external model for a themed set and have it resolved against what they actually own.

### 4.7 `__init__.py` — the public entry point

Exposes one coroutine, `async_generate_library_playlist(hass, *, size, difficulty_slider, popularity_percent, genres, min_confidence, balance_decades, exclude_uris)`.

It loads the cached pool, **recomputes `familiarity_band` from percentiles on load** (so pools built by older, miscalibrated versions are corrected without a rescan), maps `popularity_percent` → percentile window (`P` → `[1 - P/100, 1.0]`), calls the generator, then records diagnostics in two places:

* one INFO log line per generation (`Library generate: size=… eligible=… widened=… expanded=…`)
* `hass.data[DOMAIN]["library_last_generate"]`, which the admin panel renders as a "Last game generated" row

That second sink exists because `logger.set_level` resets on every HA restart, which repeatedly made log-based verification vanish exactly when a user needed it. **The panel must be able to explain a game without log access.**

The module uses a lazy `__getattr__` so importing the package doesn't drag in `aiohttp`-heavy submodules at HA startup. `tools/check_imports.py` understands this and still enforces that CONSTANT-style names really exist (§12.1).

### 4.8 `backup.py` — backup, restore and merge

Pure logic behind the panel's Backup/Restore buttons; the HTTP plumbing lives
in `library_views.py`.

* `build_backup_bundle()` — wraps the pool **and** the library settings, so
  restoring on a fresh install brings back the configuration too, not just the
  data.
* `validate_backup_bundle()` — refuses non-objects, missing song lists,
  malformed entries, implausible sizes and newer schema versions. It also
  **accepts a bare `library_pool.json`**, because that hand-copied file was
  the only backup possible before this feature existed and users should not be
  told it is invalid.
* `merge_pool_entries()` — unions two pools by track URI. The winner is chosen
  by `_entry_rank()`: year confidence first, then presence of popularity, then
  genres, then genre-check version. This makes a merge **monotonic** — it can
  only improve an entry, never trade a MusicBrainz-verified year for a tag year
  because the other file happened to be newer.
* `describe_bundle()` — summary for the confirmation UI.

Two invariants the HTTP layer must uphold, and does:

1. **Re-finalize after any merge.** Percentiles and familiarity bands are
   pool-relative; carrying them across from a file would silently corrupt the
   popularity window. The restore path runs the merged entries through
   `finalize_pool()`.
2. **Stash before overwriting.** A restore is destructive, so the current pool
   is copied to `library_pool.pre-restore-<timestamp>.json` first and the name
   is reported back to the UI.

The restore endpoint caps both the compressed upload (128 MB) and the
decompressed payload (512 MB) — a gzip bomb would otherwise be an easy
memory-exhaustion vector — and does all compression, decompression and JSON
work in an executor, never on the event loop.

---

## 5. Data model & persistence

### 5.1 The pool file

`/config/beatify/library_pool.json` — schema in §4.4. Written atomically via `_write_pool()`. It is the only large artifact this provider creates; deleting it costs a rescan but nothing else.

### 5.2 Library game settings (HA Store `beatify.library_settings`)

Written by the admin panel on every change, read server-side at generation time. Keys:

| Key | Type | Meaning |
|---|---|---|
| `size` | int | songs per game (clamped to the game's min/max) |
| `difficulty` | int 0–100 | coarse familiarity band (legacy control, still honoured) |
| `popularity_percent` | int 1–100 | "draw from the most-popular P%" — the precise control |
| `year_gate` | `"strict"` \| … | maps to a `YearConfidence` minimum |
| `genres` | list[str] | selected genre chips (max 20) |
| scan-related keys | mixed | scan size, MusicBrainz on/off, Last.fm key |

Sanitisation happens in two places: `sanitize_library_settings()` on write, `_parse_library_config()` on read. Both clamp; neither trusts the client.

### 5.3 Output settings (HA Store `beatify.game_output_settings`)

Added in v0.7.17. Holds the last-known **device**, **TTS config**, and **party-lights config** pushed from the panel:

```jsonc
{
  "media_player": "media_player.living_room",
  "tts": { "enabled": true, "entity_id": "tts.piper", "announce_round_start": true,
           "tts_pre_round_delay": 12.0, … },
  "party_lights": { "enabled": true, "entity_ids": ["light.a","light.b"],
                    "intensity": "party", "light_mode": "dynamic", "wled_presets": … }
}
```

This Store exists because the client chain is *not* reliable: the force-reset flow wipes all Beatify `localStorage` (including `beatify_tts` and `beatify_party_lights`), reloads the page, and auto-creates a room — a create racing wiped-then-rewritten storage, with a token reset that can 401 an in-flight push. Server-side persistence plus a server-side re-apply at start makes the client's reliability irrelevant. Full story in §10.2.

### 5.4 Ephemeral state (`hass.data[DOMAIN]`)

| Key | Purpose |
|---|---|
| `library_last_generate` | summary of the last generation, rendered by the panel |
| recently-played URIs | rolling window feeding `exclude_uris` (repeat avoidance across games) |

Both are intentionally **not** persisted: they are conveniences, and a restart resetting them is harmless. Note that the recent-play window is what makes `excluded_recent=…` climb in the logs; on a very narrow popularity window with rapid back-to-back testing it can legitimately drive `eligible` to 0 and force widening. That is the guard working, not a bug (§15.3).

### 5.5 Playlist output (fed to upstream `PlaylistManager`)

```jsonc
{
  "name": "Your Library: Crowd-Pleasers (30 songs)",
  "version": …, "_generated": …, "tags": [...],
  "songs": [
    { "year": 1982, "title": "…", "artist": "…",
      "uri_ma_library": "plex--…://track/…",
      "album": "…", "alt_artists": [...],
      "_global_score": 71.4, "_popularity_percentile": 0.98,
      "_year_source": "musicbrainz" }
  ],
  "_eligible_count": 82, "_window_widened": false, "_genres_expanded": []
}
```

Underscore-prefixed song keys are debugging breadcrumbs; the game ignores them. `_eligible_count`, `_window_widened` and `_genres_expanded` are consumed by the panel and the log line.

---

## 6. HTTP API reference

All endpoints are registered in `custom_components/beatify/__init__.py` and authorised in-handler via `is_authorized_http()` (which supports the Companion-app bypass, upstream #1131). Library endpoints live in `server/library_views.py`; `UpdateLobbyView` lives in `server/game_views.py` because it manipulates game state.

| Method | Path | Purpose |
|---|---|---|
| GET | `/beatify/api/library-pool` | Pool status: counts, usable count, progress, stats, refresh backlog |
| POST | `/beatify/api/library-pool/build` | Start/extend a scan (size, MusicBrainz on/off, Last.fm key) |
| POST | `/beatify/api/library-pool/refresh` | Background refresh pass: re-resolve years, re-verify popularity |
| GET | `/beatify/api/library-pool/preview` | **Live match count** for the current settings (drives the red warning) |
| GET | `/beatify/api/library-pool/export` | Compact index for AI curation |
| GET/POST | `/beatify/api/library-settings` | Shared server-side game settings (§5.2) |
| POST | `/beatify/api/library-playlists/resolve` | Resolve AI-returned picks against the pool |
| POST | `/beatify/api/library-playlists/generate` | Generate and save a named library playlist |
| GET | `/beatify/api/library-pool/backup` | Download pool + settings as one gzipped bundle |
| POST | `/beatify/api/library-pool/restore` | Restore a bundle (`?mode=replace\|merge`) |
| POST | `/beatify/api/game/update-lobby` | **Apply device / TTS / lights to the live game** and persist them |

### 6.1 `POST /beatify/api/game/update-lobby`

The most important new endpoint. Body (all keys optional):

```jsonc
{ "media_player": "media_player.x",
  "tts": { … } | null,
  "party_lights": { … } | null }
```

Behaviour:

* No game, or game not in `LOBBY` / `PLAYING` / `REVEAL` → `{"updated": false}`. This makes it safe to fire-and-forget from the UI without tracking game state.
* `media_player`: validated against the entity registry **and** the platform-capability table, then applied — including nulling `_media_player_service` so the cached service doesn't keep routing to the old device.
* `tts` / `party_lights`: applied through `_apply_tts_config()` / `_apply_party_lights_config()`, which unpack the frontend config dicts exactly the way the create endpoint does. A **present-but-falsy** value means *explicit disable* (`disable_tts()` / `disable_party_lights()`), not "ignore".
* Every accepted field is persisted to `beatify.game_output_settings` so the pre-start hook can re-apply it on any start path.

Response: `{"updated": true, "fields": ["media_player", "tts", "party_lights"]}`.

The distinction between "key absent" and "key present but falsy" is load-bearing — conflating them is precisely how a disabled TTS kept announcing (§10.2).

---

## 7. Modifications to upstream files

This is the complete list. Everything else in the tree is untouched upstream code.

| File | Change | Why |
|---|---|---|
| `const.py` | `PROVIDER_MA_LIBRARY`, `URI_PATTERN_MA_LIBRARY` | Register the provider; permissive URI pattern for MA library URIs |
| `__init__.py` | Import + register 8 library views and `UpdateLobbyView`; register the `beatify.build_library_pool` HA service | Wiring |
| `server/library_views.py` | **New file** | All library endpoints + the two Stores |
| `server/game_views.py` | Library game creation, `_generate_library_songs`, `_parse_library_config`, `pre_start_hook` injection, `UpdateLobbyView`, `_apply_tts_config`, `_apply_party_lights_config` | Game integration + the settings-application seam |
| `game/state_setup.py` | `replace_songs()`; create-time reset of `_tts_service` and `_party_lights` | Song regeneration; stale-service fix |
| `game/state_lifecycle.py` | `pre_start_hook` firing; TTS resume watchdog | Settings seam; device resume |
| `game/playlist.py` | `uri_ma_library` branch in `get_song_uri()` + URI pattern entry | Playback URI resolution |
| `game/serializers.py` | `state["server_now_ms"]` | Clock-skew fix for the round counter |
| `services/media_player.py` | `ma_library` capability + URI mapping; name-fallback play; `enqueue: "replace"`; pre-play volume re-assert | Playback correctness |
| `www/admin.html` | Library settings mount point, wizard step-3 container, `library.min.css` link, provider chip | UI |
| `www/js/admin.js` | Library config in the create payload; config push at Start; skew-corrected admin countdown | UI wiring |
| `www/js/admin/sections/library.js` | **New file** — the entire library panel | UI |
| `www/js/admin/sections/library-ai.js` | **New file** — AI curation modal | UI |
| `www/js/admin/sections/media-players.js` | Push device change to the live game | Settings seam |
| `www/js/admin/sections/game-settings.js` | Push output settings on save | Settings seam |
| `www/css/library.css` | **New file** — panel styles incl. the low-match warning | UI |
| `www/i18n/en.json`, `de.json` | New keys under `admin.library.*` and the wizard step | i18n |
| `www/sw.js` | Cache suffix bumps (`-mylibNN`) | Cache busting |

### 7.1 `game/playlist.py`

`get_song_uri()` gains a branch returning `song.get("uri_ma_library")`, and the URI-pattern table gains `("uri_ma_library", URI_PATTERN_MA_LIBRARY, "library://track/{id}")`.

**Rebase hazard:** this branch has been silently dropped by a rebase before (fixed in v0.5.5, guarded ever since). `tests/test_smoke.py` asserts its presence. If a future rebase removes it, every library game will resolve no URIs and appear to be "no playable songs" — a confusing failure with an easy cause.

### 7.2 `game/state_setup.py`

**`replace_songs(songs)`** swaps the song list while still in `LOBBY`. It rebuilds the `PlaylistManager` exactly as `rematch_game` does — same storefront re-detection, same `total_rounds` derivation from the playable pool (upstream #1377) — and returns `False` if the new set has no playable songs, in which case the game keeps its creation-time songs.

**Create-time service resets.** Upstream nulls `_media_player_service` in `create_game` and documents why (the lazily-built service captures its entity at construction and would otherwise be recycled). We apply the identical reset to `_tts_service` and `_party_lights`. Without it, a new game with TTS *disabled* kept announcing on the *previous* game's device, because `configure_tts` is only called when a config is supplied — so nothing ever cleared the old service (§10.3).

### 7.3 `game/state_lifecycle.py`

Two additions.

**Pre-start hook** — at the top of `start_round()`:

```python
hook = getattr(self, "pre_start_hook", None)
if hook is not None and self.phase == GamePhase.LOBBY and _retry_count == 0:
    try:
        await hook(self)
    except Exception:
        pass                      # a hook failure must never block the game
    self.pre_start_hook = None    # fire once per game
```

Three properties matter: it fires **once**, only on the `LOBBY → first round` transition, and only for games that carry a hook (saved-playlist and other-provider games are untouched). A hook exception is swallowed deliberately — the worst case must be "the game plays its creation-time songs", never "the game won't start".

**TTS resume watchdog** — armed after the announcement chain when a TTS service and media player are present. Final logic (v0.7.22):

* Polls once per second for 20 s.
* Kicks `media_player.media_play` when the state is `paused`, **or** when it has been `idle` with a loaded title for 3 consecutive polls.
* Exits on `off`, on entity disappearance, after 3 kicks, or at the end of the window.
* Logs every observation at INFO (`Resume watchdog[NN]: state=… title=…`) and every kick at WARNING.
* **Retains its task reference** on the game state (`self._tts_resume_task`), cancelling any previous one and clearing itself in a done-callback.

That last point is not stylistic. `asyncio.create_task()` results are held only weakly by the event loop; an unreferenced task can be garbage-collected before it runs, and that is exactly what happened — the watchdog produced zero log lines for three releases because it was being collected (§10.5).

### 7.4 `game/serializers.py`

Adds `state["server_now_ms"] = int(time.time() * 1000)` next to `state["deadline"]`, so deadline-driven client counters can correct for device clock skew. Upstream already acknowledges this hazard for the title/artist vote window (it sends server-computed seconds there); the round counter simply never received the same treatment (§10.7).

### 7.5 `services/media_player.py`

* **Capability + URI mapping:** `"ma_library": True` in the platform-capability table and `"ma_library": ("uri_ma_library",)` in the provider→URI-field map.
* **Name fallback:** for `ma_library`, the play call passes `artist` alongside `media_id` so MA's resolver can disambiguate when a stored URI has gone stale (library rebuilds change IDs).
* **`enqueue: "replace"`:** every round's track replaces the MA queue. Without it, rounds accumulate in the queue and a post-announcement resume can advance into stale entries — observed as a player returning to earlier rounds' songs, sometimes mid-round (§10.6).
* **Pre-play volume re-assert:** immediately before starting a stream, the device is re-synced to HA's known `volume_level`. Some devices begin a new stream at their own default level and only settle after an external correction, producing a one-second full-volume scare (§10.8).

---

## 8. Frontend modifications

### 8.1 Build discipline

`admin.html` loads a **bundled** `js/admin.min.js` (`type="module"`) and `css/library.min.css`. Editing raw sources without rebundling changes nothing at runtime — a trap worth knowing before you spend an hour debugging a fix that was never shipped.

```bash
npx -y esbuild js/admin.js --bundle --minify --format=esm --outfile=js/admin.min.js
npx -y esbuild css/library.css --minify --sourcemap --outfile=css/library.min.css
```

Then bump the `-mylibNN` suffix in `sw.js` and hard-refresh once. `tests/test_smoke.py` verifies that key strings are present **in the bundle**, not just in the sources, precisely because "fixed but not rebundled" is an easy and invisible mistake.

### 8.2 `library.js` — the panel

Mounted into `#library-settings` (main settings) and `#wiz-library-root` (wizard step 3); `mountLibraryPanel(rootEl, {mode})` renders both. Responsibilities:

* Scan/refresh controls with live progress polling
* Pool statistics: track count, usable count, year-source breakdown, refresh backlog
* Game controls: size, "Top P%" popularity slider, year-strictness gate, genre chips
* **Live match count** via `/library-pool/preview`, turning **bold red** with a warning when fewer songs match than the game needs
* **"Last game generated"** row: what the last game actually used, including `+ related: House, Dance` when the adjacency fallback fired
* Provider version display
* Multi-instance sync (`_syncSiblings`) so the wizard and settings copies stay consistent
* Persists every change to the server Store immediately

### 8.3 `library-ai.js` — curation

Builds a prompt from the pool export index, accepts a pasted model answer, parses picks (`parseAiAnswer`), resolves them server-side, and saves the result as a named playlist. Deliberately transport-free: the user brings their own model, no API key is stored, nothing leaves HA except what the user copies.

### 8.4 Settings pushes

Three call sites now POST to `/beatify/api/game/update-lobby`:

1. `media-players.js` — on device selection
2. `game-settings.js` — on settings save
3. `admin.js` — **in `startGameplay()`, awaited, immediately before the phase flip**

The third is the important one: it is the last moment at which the browser's settings are known to be final. All three are fire-and-forget-safe because the server no-ops when no game exists. Even so, the client push is only *belt*; the braces are the server-side re-apply from the Store in the pre-start hook (§3.3).

### 8.5 The countdown skew fix

`startAdminCountdown(deadline, serverNowMs)` computes `clockSkewMs = serverNowMs - Date.now()` once per state receive and applies it on every tick. The player-facing counter has not been changed; if players report the same phantom-time symptom, it needs the identical one-line treatment.

---

## 9. Design decisions and their rationale

Each of these was a fork in the road. They are documented so a future maintainer can revisit them deliberately rather than accidentally.

### 9.1 External years are authoritative; tags are not

**Decision:** default gate = `EXTERNAL_PRIMARY` (MusicBrainz, match-verified). Tag years are available only by explicitly relaxing the gate.

**Why:** in real libraries, tag years are wrong often enough to ruin the game, and wrong in a *biased* way — compilations systematically report the pressing year, so an entire era of music appears to be from the 1990s. A year-guessing game whose answers are wrong is worse than no game.

**Cost:** usable pool size is much smaller than library size. Accepted deliberately; the panel shows both numbers so users understand the gap.

### 9.2 Popularity means *worldwide* popularity

**Decision:** normalise external signals onto a 0–100 global fame scale rather than ranking within the library.

**Why:** the difficulty slider must mean the same thing for every host. Ranking within a library makes "easy" mean "the least obscure of my obscurities" — a jazz collector's "easy" round would be unplayable for guests.

### 9.3 …but the *window* is a percentile, with an absolute floor

**Decision:** "Top P%" selects a percentile window within the pool, **and** for narrow windows (`lo >= 0.5`) additionally requires `global_score >= 40 + 30·lo`.

**Why:** the percentile alone is relative — in a rarity-heavy library, "top 5%" still surfaces the least-obscure of the obscure. The absolute floor alone would be unusable — in a modest library, nothing might clear it. The hybrid gives a control that behaves intuitively ("more popular" really does mean more famous) while remaining functional on every library. The formula scales the demand with the narrowness of the request: `lo=0.95` → floor ≈ 68.5; `lo=0.7` → ≈ 61; wide windows (`lo < 0.5`) → no floor at all, because deep cuts are the point there.

### 9.4 Scarcity degrades along musical neighbourhoods

**Decision:** when a filtered window can't fill a game, fill from **adjacent genres in the same popularity window** before widening down the ranking.

**Why:** this was the user's own proposal, and it is better than the widening it precedes. Observed failure: "Top 5% Trance" (18 eligible) filled with Michael Jackson, Pet Shop Boys and Hans Zimmer. Those weren't random — they were the *most famous* songs carrying a leaked "Trance" tag from dance-compilation albums. Genre pollution plus fame-sorting is a reliable machine for producing absurd results. Filling with top-5% House/Dance/Electro instead gives a trance fan something recognisable and adjacent.

`GENRE_RELATED` covers ~35 coarse genres, case-insensitive, symmetric where it should be. Unknown genres map to nothing, so the map degrades safely. Extending it is the safest possible contribution: add a key, add a test.

**Fallback order, in full:**

```
exact genre ∩ window  →  related genres ∩ window  →  widen down the ranking
  →  unknown-popularity (only if hi ≥ 0.66)
```

### 9.5 The server is authoritative for everything a game needs

**Decision:** settings live in HA Stores; the client is a convenience layer.

**Why:** every settings-related bug in this project (§10.1, §10.2) came from trusting the browser. `localStorage` gets wiped by force-reset, tokens reset, page loads race room creation, and stale bundles linger in service-worker caches. A server that reads its own Store at the moment of use is immune to all of it. The pre-start hook is the concrete expression of this principle.

### 9.6 Diagnostics belong in the UI, not only in logs

**Decision:** the panel shows the live match count, a red low-match warning, and a "Last game generated" summary.

**Why:** `logger.set_level` resets on every HA restart, so log-based verification kept evaporating. A user should be able to answer "why did my game contain that?" without SSH.

### 9.7 Repeat avoidance never blocks a game

**Decision:** recency exclusion applies only if enough songs remain afterwards.

**Why:** the alternative is a game that cannot be created after heavy testing. The visible consequence — `excluded_recent` climbing and forcing widening during rapid back-to-back tests — is the correct trade.

---

## 10. The bug chronicle: root causes and permanent fixes

This section exists so nobody re-derives these. Each entry gives the **symptom**, the **actual mechanism**, and the **fix**, plus the guard that prevents regression.

### 10.1 The songs off-by-one (v0.7.9 → v0.7.10)

**Symptom:** changing popularity or genre took effect one game late. Selecting "Top 5% Rock" produced the *previous* selection's songs; the Rock game appeared only on the next start.

**Mechanism:** songs are sampled at **room creation**. The lobby's reset button creates the next room immediately, so any change made afterwards missed its own game.

**First fix (v0.7.9, incomplete):** regenerate songs in the REST `/start-gameplay` view. This worked — for that path only. The websocket admin handler calls `start_round()` directly, and the bug survived there.

**Final fix (v0.7.10):** move regeneration into a `pre_start_hook` fired from `start_round()` itself, which every start path funnels through. The hook is injected at create time for generated library games only.

**Guard:** `test_smoke.py` asserts both the injection and the fire-once semantics.

**Lesson:** when a bug survives a correct-looking fix, the question is not "is the logic right?" but "does this code path actually execute?"

### 10.2 The reset-path config lag (v0.7.11 → v0.7.18)

**Symptom:** device, TTS and party-lights settings applied one game late — but *only* when the lobby's reset button was used. Starting a new game from the results screen worked.

This took five releases and was, in the end, two independent problems stacked.

**Problem A — architecture.** Configs were pushed from the browser only. Reading upstream's `force-reset.js` explained the asymmetry: reset **wipes all Beatify `localStorage`** (including `beatify_tts` and `beatify_party_lights`), reloads, and the home view auto-creates a room. That path races wiped-then-rewritten storage and resets the admin token, which can 401 an in-flight push. The results-screen path is a clean create with settled storage — hence it worked.

*Fix:* persist every push into `beatify.game_output_settings` and **re-apply them server-side in the pre-start hook**. Whatever was last saved wins, on every path.

**Problem B — a missing import.** With the architecture correct, the symptom persisted. The user's log capture showed a single traceback frame: `game_views.py, line 789, in post`. The cause was `with contextlib.suppress(...)` **without a module-level `import contextlib`** — an earlier automated edit had checked "does the file contain `import contextlib`?", matched a *local aliased* import inside an unrelated function, and skipped adding the real one.

The consequences were beautifully consistent with the symptoms: every update request applied the media player (logged), then died at the first `contextlib` line — so TTS/lights were never configured, nothing was persisted, the pre-start re-apply found an empty Store, and the watchdog never armed. Three architecturally correct fixes were strangled by one missing line. The exception text contained no "beatify", so it did not appear in the user's greps.

*Fix:* the import. *Guard:* `test_smoke.py` now fails if a module name is used via attribute access without a module-level import.

**Lesson:** when a fix "changes nothing", suspect that it isn't running. Ask for a raw log tail rather than a filtered one — the filter is what hid this for three releases.

### 10.3 The split-brain game (v0.7.15)

**Symptom:** new game on the satellite with TTS **disabled** — music on the satellite, announcements still on the *previous* game's ShieldTV.

**Mechanism:** `create_game` nulls `_media_player_service` but not `_tts_service`. With TTS disabled, `configure_tts` is never called, so the previous game's service — enabled and bound to the old device — survived wholesale into the new game.

**Fix:** apply upstream's own documented reset pattern to `_tts_service` and `_party_lights`. **This is an upstream bug affecting every provider** (§13.2).

### 10.4 The dict-as-entity-id crash (v0.7.19)

**Symptom:** after §10.2 was fixed, logs showed `services/tts.py, line 81, in speak` on every round, plus `Party Lights phase change failed` and a phantom "Party Lights started: 4 lights" when the user had a different number of lights.

**Mechanism:** `configure_tts()` takes the TTS **entity id** as its first positional argument plus unpacked `announce_*` keywords; `configure_party_lights()` takes `(entity_ids, intensity, light_mode, wled_presets)`. Our update endpoint passed the **raw frontend config dicts**. Python accepted this silently. TTS then crashed inside `speak()` at `hass.states.get(<dict>)`, and party lights iterated the dict's **keys** as entity ids — the "4 lights" were four config-key strings, after which every phase change failed against entities that don't exist.

**Fix:** shared `_apply_tts_config()` / `_apply_party_lights_config()` helpers that unpack exactly as the create endpoint does, used by both the update endpoint and the pre-start hook. **Guard:** smoke checks ban raw-dict `configure_*` calls outright.

**Lesson:** duck typing plus broad `except` clauses can turn a type error into a mysterious behavioural bug three layers away. Where two call sites must build the same object, extract one builder.

### 10.5 The TTS resume watchdog (v0.7.14 → v0.7.22)

**Symptom:** on Music Assistant **voice satellites**, a round would start, the announcement would play, and the music would never resume. Pressing play manually in MA worked. ShieldTV was unaffected.

Four iterations, each teaching something:

| Version | Approach | Why it failed |
|---|---|---|
| v0.7.14 | Check once ~2.5 s after the announcement chain; return if not `paused` | At that moment the *announcement itself* is still playing, so it always returned before the pause occurred |
| v0.7.17 | Poll for 20 s, kick whenever `paused` | Never ran at all — see below |
| v0.7.21 | Narrate every observation; also kick on "playing with frozen position" | Narration revealed the truth; the stall heuristic was wrong |
| v0.7.22 | Kick on `paused` **or** sustained `idle` with a title | Correct; hardware-verified |

Two distinct root causes, both instructive:

**Cause 1 — garbage collection.** v0.7.17 armed correctly but produced *zero* log lines. `asyncio.create_task()` returns a task the event loop holds only **weakly**; without a retained reference it can be collected before running. The task is now stored on the game state, with the previous one cancelled and a done-callback clearing it.

**Cause 2 — the wrong state name.** The narrating build showed the satellite sitting in **`idle`** for 16 consecutive seconds with the title still loaded — while MA's own UI displayed a paused track. HA's entity never reports `paused` for this device at all. Worse, the v0.7.17 watchdog *explicitly tolerated* `idle`, so it watched the exact failure it was built to catch.

The same narration also disproved the frozen-position heuristic: MA reports `media_position` as a **snapshot plus timestamp** (HA derives the live position), so a frozen `pos` with periodic `updated_at` refreshes is *healthy playback*. That heuristic was kicking a perfectly working ShieldTV three times per round and was removed.

Final behaviour: 1 Hz polling for 20 s; kick on `paused` or `idle_streak >= 3` with a loaded title; up to 3 kicks; exit on `off`/timeout. Resume now takes ~2–3 s after the announcement, hands-free.

**Note:** satellites also flap `playing → idle → playing` for single ticks during healthy playback. The 3-tick requirement makes those blips harmless, and no PLAYING-phase listener ends rounds on `idle`. If you tighten the threshold to 2 ticks (≈1 s faster resume), be aware you are trading against those blips — though a spurious `media_play` on a playing device is a no-op.

### 10.6 ShieldTV time-travel (v0.7.20)

**Symptom:** the ShieldTV would return to *previous rounds'* songs, sometimes mid-round.

**Mechanism:** the MA `play_media` call sent no `enqueue` mode, so every round's track was **added** to the queue. After a TTS interrupt, MA's queue-resume could advance into stale entries. The player was faithfully resuming a queue full of history.

**Fix:** `enqueue: "replace"` on every play. The queue now contains exactly the current song, so any resume can only resume *that* song. This likely also improves resume behaviour on other devices, since a one-song queue is a much simpler resume target.

### 10.7 The phantom early "time's up" (v0.7.23)

**Symptom:** the admin counter showed ~20 s remaining at the exact moment the server declared time-up.

**Mechanism:** the counter derives remaining time from the server's absolute `deadline` against the **client device's clock**. A tablet whose clock is ~20 s off displays exactly that much phantom time. The server ran rounds at full length throughout; only the display lied.

**Fix:** stamp `server_now_ms` into the state payload; the client computes skew once per state receive and corrects each tick. Upstream already does the equivalent for the title/artist vote window — this simply extends the same protection to the round counter.

**Separate but related:** the *audible music* window genuinely does shrink when announcements are enabled, because the round deadline starts at round init while the announcement chain consumes 8–25 s. That is not a bug; upstream's **"Timer delay"** setting (`tts_pre_round_delay`, issue #1211) exists precisely for it. Recommended ≈12 s, or ≈18 s with countdown announcements enabled. Our pipeline forwards the value through push → Store → pre-start re-apply.

### 10.8 The volume scare (v0.7.13)

**Symptom:** songs started at full volume and dropped within a second.

**Investigation:** upstream's play path contains **no** volume logic at round start (`set_volume` serves only the host buttons and the end-of-game restore, #1516), and our provider never touched volume. So the spike originates below Beatify: either the device starts each new stream at its own default level, or — when TTS announcements are enabled — MA's announce-duck restore lands after the song has already started.

**Mitigation:** re-assert HA's known `volume_level` immediately **before** starting a stream. A no-op on well-behaved players; closes the window on devices that reset per stream. The MA announce-duck path remains outside our control.

### 10.9 Smaller fixes worth knowing

* **v0.5.5** — a rebase silently dropped the `ma_library` branch in `get_song_uri()`. Now smoke-guarded.
* **v0.5.1 / v0.6.1** — import errors at HA startup (a view import, then a bad `ENGINE_VERSION` import) prevented the whole integration from loading. This class is why `tools/check_imports.py` exists.
* **v0.7.2** — the refresh path crashed on names scoped to the build closure. Shared helpers were extracted to module level.
* **v0.6.3** — additive scans re-counted cached tracks (a "1 000-song scan" reporting 16 000).
* **v0.7.4** — genres measured as *never* present on MA list models (20 000 fetches → 0), forcing the detail-fetch design.
* **v0.7.13** — the low-match warning was bold but not red: a CSS specificity fight against the base `hint-text` rule, which sets `color` but not `font-weight`.

---

## 11. Device and platform quirks matrix

Empirically established on the author's hardware (HAOS/Core 2026.7.x, Music Assistant 2.9.9).

| Device | Behaviour | Handling |
|---|---|---|
| **MA voice satellites** | Do not auto-resume after an announcement; sit in HA state `idle` (never `paused`) with the title loaded; flap `playing↔idle` for single ticks during healthy playback | Resume watchdog kicks on 3 consecutive idle ticks (§7.3) |
| **ShieldTV (Android TV)** | Resumes correctly; accumulated queue caused song time-travel; plays both round-start *and* countdown announcements | `enqueue: replace`; disable the countdown announcement if one is enough |
| **Echo devices** | Work; some may reset volume per stream | Pre-play volume re-assert |
| **Tablets (admin view)** | Device clock can drift tens of seconds | Skew-corrected countdown |
| **All MA players** | `media_position` is a snapshot + timestamp, not a live counter | Never treat a frozen position as a stall |

**MA version note:** 2.9.5 → 2.9.9 changelogs were reviewed for impact on our surface (client API, `play_media` semantics, announce/resume). No impact found; notably, nothing in that range fixes satellite announce-resume, so the watchdog remains necessary.

---

## 12. Testing, tooling and release discipline

### 12.1 `tools/check_imports.py`

Static AST verification of every intra-package `from … import …` — relative *and* absolute (`custom_components.beatify.…`). For each import it resolves the target module and confirms the name is actually defined. Special handling:

* Modules with a lazy `__getattr__` (PEP 562) are tolerated **except** for CONSTANT-style and dunder names, which are never lazily generated here — that exact gap once shipped a boot-blocking `ENGINE_VERSION` import.
* `from package import submodule` is recognised as valid when the submodule file exists.

It exists because **an import error at HA startup prevents the entire integration from loading**, and `py_compile` cannot see it. It has caught real boot-blockers, including one in the very release that introduced `UpdateLobbyView` (registered but not re-exported through the `server/views.py` aggregator).

### 12.2 Our pytest suites (93 tests under `tests/unit/`)

Ported into upstream's own harness, so `pytest tests/unit/` runs them alongside
its 1623 tests. The root `conftest.py` stubs Home Assistant, so the pure modules
import without a running HA.

* **`test_library_generator.py`** (17) — selection behaviour: trust gate,
  popularity window, genre adjacency, repeat avoidance, dedupe. Real
  behavioural tests, not source guards.
* **`test_library_metadata.py`** (44) — compilation detection, MusicBrainz
  title candidates and earliest-year selection, logarithmic popularity
  scaling, percentile assignment, backup validation and pool merging.
* **`test_library_regressions.py`** (32) — structural guards for bugs that
  only reproduce on real devices (announcement timing, resume behaviour,
  queue semantics, bundle drift). Each guard's docstring states the bug it
  prevents, so the file doubles as the device-quirk history.

Coverage of the library package: `backup` 83%, `generator` 70%,
`year_resolver` 57%. **`ma_client`, `pool` and `matcher` are at 0%** — they are
network I/O against Music Assistant, MusicBrainz and Deezer, and testing them
needs a mocked client. That is the most valuable open contribution.

### 12.3 `tools/check_imports.py`

Static AST verification of every intra-package import, resolving both relative
and absolute forms and confirming each imported name exists. It exists because
an import error at HA startup prevents the WHOLE integration from loading, and
`py_compile` cannot see it. During the 4.2.0 rebase, `ruff` caught five
undefined names this checker's sibling rules had not yet been extended to
cover — both tools earn their place.

### 12.4 The release gate

```bash
find custom_components -name "*.py" -exec python3 -m py_compile {} +
python3 tools/check_imports.py
python3 tests/test_smoke.py
python3 tests/test_generator_related.py
# if JS changed: node --check <files> + rebundle + grep the bundle
```

**Green before packaging.** In one release the gate failed on a stale guard that still expected a now-banned pattern — exactly the intended behaviour, caught before shipping.

### 12.5 Packaging

Every release ships a full installer zip containing `custom_components/`, **`tools/`**, **`tests/`**, `install.sh`, and the docs. Shipping the tooling inside the artifact is a hard rule: development environments have been lost twice, and each time the workspace was reconstructed from the latest zip. A zip without `tools/` and `tests/` is a zip that loses the safety net.

After zipping, contents are verified by extracting key files and grepping for the release's markers (version string, new symbols, bundle strings, cache suffix) — "it built" is not the same as "it contains the fix".

### 12.6 Version and changelog

`library/version.py` holds `__version__` and the **complete annotated changelog** — currently ~700 lines documenting every release from 0.1.0 to 0.7.23, including root causes. It is the primary historical record; this document is its distillation. Bump both on every release.

### 12.7 Recommended test suite work

The original pure-logic suite (162 checks over the year resolver, popularity math, generator, and matcher) was lost in an environment reset before tooling was shipped inside artifacts. Its contents are recoverable from session history. **Rebuilding it incrementally is the single highest-value contribution** a new maintainer could make — the current suites guard against regressions but do not broadly verify the engine's logic. Priorities: `year_resolver` compilation detection and candidate generation, `popularity` scaling and percentile assignment, `generator` window/fallback ordering.

---

## 13. Upstreaming guide (for mholzi)

### 13.1 Suggested PR strategy

The work divides cleanly into two categories, and they should almost certainly be **separate pull requests**.

**PR 1 — provider-neutral fixes (small, high value, low risk).** Five changes that fix real bugs for *every* provider and are independent of the library feature (§13.2). Each is a few lines. These stand alone and could merge immediately.

**PR 2 — the library provider itself (large, additive).** The `library/` package, `library_views.py`, the panel, and the game-integration touchpoints. Additive by construction: when the provider isn't selected, no new code path executes.

Sequencing PR 1 first makes PR 2 much easier to read, since several of the touchpoints in `game_views.py` and `state_lifecycle.py` would otherwise be entangled with the fixes.

### 13.2 Provider-neutral fixes worth taking regardless

| Fix | File | Bug it fixes |
|---|---|---|
| Reset `_tts_service` / `_party_lights` in `create_game` | `game/state_setup.py` | A new game with TTS disabled keeps announcing on the previous game's device (§10.3) |
| TTS resume watchdog (or announce-before-play ordering) | `game/state_lifecycle.py` | MA voice satellites never resume after an announcement — the round is silent (§10.5) |
| `enqueue: "replace"` on MA `play_media` | `services/media_player.py` | Rounds accumulate in the MA queue; resume can jump to earlier songs (§10.6) |
| `server_now_ms` + skew-corrected countdown | `game/serializers.py`, `www/js/admin.js` | Phantom "time's up" on devices with a drifted clock (§10.7) |
| Pre-play volume re-assert | `services/media_player.py` | One-second full-volume scare at round start on some devices (§10.8) |

The first three are, in the author's view, worth taking even if the library provider never merges: they are real defects with small fixes and clear hardware evidence.

### 13.3 Before merging: the rebase

This work is based on 4.2.0-rc9 (`db91033`); upstream is at 4.2.0-rc13 or later. A raw diff against current upstream shows ~90 files, **mostly upstream's own progress**, not our changes. The rebase is therefore a genuine task and the last substantial roadmap item.

Recommended procedure:

1. Clone pristine upstream to a separate directory.
2. Apply our changes file-by-file using §7's table as the checklist, re-reading each upstream function before re-applying (several of our touchpoints are inside functions upstream has since edited).
3. Copy `library/`, `server/library_views.py`, and the new `www` files wholesale — they have no upstream counterpart and cannot conflict.
4. Run the full gate (§12.4), especially `check_imports.py`: the aggregator re-export in `server/views.py` is exactly the kind of thing a rebase drops.
5. Verify on hardware: one library game with TTS + lights on a satellite, one on another player type.

### 13.4 Review notes / risk assessment

* **Blast radius when unused:** the pre-start hook only fires for games that carry one; `UpdateLobbyView` no-ops without an active game; the watchdog arms only when a TTS service *and* a media player are present; `enqueue: replace` and the volume re-assert affect all MA playback (deliberately — they are fixes).
* **New dependencies:** none.
* **External calls:** MusicBrainz and Deezer, only during pool build/refresh, never during a game. MusicBrainz is called with a proper UA and rate limiting.
* **Storage:** one JSON pool under `/config/beatify/`, two HA Stores.
* **Privacy:** track titles and artists are sent to MusicBrainz/Deezer during enrichment. Worth a line in user-facing docs.
* **i18n:** English and German are complete; other languages need the `admin.library.*` keys and the wizard step.
* **Naming:** the provider id is `ma_library`; the user-facing name is "Crate Digger". Rename freely — the id appears in `const.py`, the capability tables, `playlist.py`, the provider chip in `admin.html`, and the panel visibility logic.

### 13.5 Things the author would want a reviewer to challenge

Offered honestly, because a fresh reviewer should not assume these are settled:

* The absolute-floor formula (`40 + 30·lo`) is empirically tuned on one library. It works, but it is a heuristic without a principled derivation.
* `GENRE_RELATED` is hand-curated and reflects one person's musical intuitions. It should probably be reviewed by someone with different taste, and possibly moved to a data file.
* The watchdog polls at 1 Hz for 20 s per round. An event-driven `async_track_state_change_event` listener would be cleaner and cheaper; polling was chosen because the state transitions in question proved surprising, and polling made them observable. Now that the signature is known, an event listener is a reasonable refactor.
* Swallowing exceptions in the pre-start hook favours "the game starts" over "the user learns something went wrong". A reviewer might prefer a visible warning.
* The pool is one JSON file. At ~300 000 tracks this will become uncomfortable; a SQLite backing store is the obvious evolution (§14).

---

## 14. Known limitations, open items, roadmap

### 14.1 Known limitations

* **Backup size.** The bundle is gzipped (~10× on a real pool), but a very
  large library still produces a multi-megabyte download; browsers handle this
  fine, mobile connections less so.
* **Pool scale.** A single JSON file is fine at ~50 000 tracks, workable at ~100 000, and will become slow to load and rewrite well beyond that. SQLite (or HA's recorder-adjacent storage) is the natural next step. The checkpoint/refresh design already assumes incremental writes, so the migration is contained to `pool.py`.
* **Enrichment throughput.** MusicBrainz rate limits dominate. A full 295 000-track library takes many sessions. The additive design makes this tolerable but not fast.
* **URI portability.** Library URIs belong to the MA server that produced them. `_config_entry_id` is stored so a mismatch can be detected; today the name-based playback fallback is what actually saves the user.
* **Genre coverage** depends on what MA/MB/Deezer return; some libraries will have sparse genres, in which case genre filtering is weak and the adjacency fallback fires often.
* **Pre-start hook scope.** It is injected for *generated library games*. A saved-playlist library game started via the reset path would not get the server-side settings re-apply. Extending injection to all game types is straightforward and probably correct.
* **Player-view countdown** has not received the skew fix (§8.5).
* **Announcement overhead** is a setting (Timer delay), not something the provider compensates for automatically. Auto-deriving it from measured announcement duration would be a nice improvement.

### 14.2 Open items at handoff

1. **Multi-round ShieldTV confirmation** that `enqueue: replace` eliminated the time-travel (single-round tests pass; a long game is the definitive check).
2. **Demote watchdog narration to `debug`** once satellites are confirmed stable across a few full games — keep the WARNING kick lines.
3. **Optional:** lower the kick threshold from 3 idle ticks to 2 for a ~1 s faster resume.
4. **Rebuild the pure-logic test suite** (§12.7).
5. **Rebase onto current upstream** (§13.3).
6. **Freeze-at-create audit remainder:** round duration, language, bonus toggles and saved-playlist selection are still creation-frozen. No lag has been reported for them (they may not be changeable while a lobby exists), but the `update-lobby` endpoint is built to be extended — add a field, apply it, persist it, re-apply it in the hook.

### 14.3 Ideas worth considering

* Event-driven watchdog instead of polling (§13.5).
* Per-genre pool statistics in the panel (how many usable songs per genre at the current gate) — would make the low-match warning predictive rather than reactive.
* A "why this song?" debug view mapping a played song back to its year source, fame score and percentile.
* Automatic Timer-delay calibration from observed announcement durations.
* Optional MusicBrainz cover-art or release-group data to improve album metadata.

---

## 15. Diagnostics cookbook

### 15.1 Enabling persistent logging

`logger.set_level` resets on restart; put this in `configuration.yaml` instead:

```yaml
logger:
  default: warning
  logs:
    custom_components.beatify: info
```

### 15.2 Reading a healthy library game

A correct start sequence looks like this (INFO):

```
Library game: no playlists selected -> generating fresh songs      ← create-time sampling
Library generate: size=30 pop_percent=5 window_min_pct=0.95 genres=['Rock']
                  eligible=299 chosen=30 excluded_recent=60 widened=False expanded=None
Game created: <id> with 30 songs
Lobby updated: media_player -> media_player.x (platform music_assistant)   ← device push
Lobby/game updated: tts configured                                  ← TTS push
Lobby/game updated: party lights configured                         ← lights push
Library generate: … (second line — the pre-start regeneration)
Library game: songs regenerated at gameplay start (30 songs, current settings)
Pre-start: tts configured                                           ← server-side re-apply
Pre-start: party lights configured
Round 1 started: Artist - Title (45.0s timer)
TTS resume watchdog armed for media_player.x
```

If any of the marked lines is missing, §15.4 tells you what it means.

### 15.3 Log-line reference

| Line | Meaning |
|---|---|
| `eligible=N` | songs matching the exact filter before any fallback |
| `widened=True` | the popularity window was widened downward (§4.5 step 7) |
| `expanded=['House','Dance']` | the related-genre fallback fired (§9.4) |
| `excluded_recent=N` | recency exclusion size; large N after rapid testing is normal |
| `Lobby updated: media_player -> …` | a device push was accepted |
| `Lobby/game updated: tts configured\|disabled` | a TTS push was accepted (or an explicit disable) |
| `Pre-start: …` | the server-side re-apply ran at first-round start |
| `TTS resume watchdog armed for …` | the watchdog task started (and is referenced) |
| `Resume watchdog[NN]: state=… title=…` | per-tick observation (demote to debug when stable) |
| `Media player idle-stuck after TTS announcement — resuming playback (kick N)` | the watchdog pressed play |
| `Party Lights started: N lights, intensity=…` | **check N against your real light count** — a wrong N meant the dict bug (§10.4) |

### 15.4 Symptom → cause table

| Symptom | Likely cause | Where to look |
|---|---|---|
| A setting applies one game late | The push isn't reaching the server, or the pre-start re-apply isn't running | Grep for `Lobby/game updated` and `Pre-start:`; a traceback frame immediately after a partial success means a mid-handler crash (§10.2) |
| Songs ignore genre/popularity | Second `Library generate` line missing → hook not firing | `test_smoke.py` hook guards; confirm the game is a *generated library* game |
| Music never resumes after TTS | Watchdog not armed, or the device's stuck state isn't `idle`/`paused` | `Resume watchdog` narration shows the true state names |
| Player revisits earlier songs | Queue accumulation | Confirm `enqueue: "replace"` is in the shipped `media_player.py` |
| Counter disagrees with the server | Client clock skew | Confirm `server_now_ms` is in the state payload and `clockSkewMs` is in the **bundle** |
| Frontend fix has no effect | Bundle not rebuilt, or the browser is serving a cached one | First grep the SHIPPED `admin.min.js` for your string — if it's absent, rebuild (`npm run build`). If it's present, the browser is stale: a hard refresh is often NOT enough. Clear site data (F12 → Application → Storage) and unregister the service worker. Note 4.2.0 keys the SW cache to the asset fingerprint, so the old manual `-mylibNN` bump is gone. Tell-tale: server-computed behaviour (e.g. sort order) looks right while newly-rendered markup is missing. |
| Integration won't load after an edit | Import error | `python3 tools/check_imports.py` |
| Games mostly filler despite a big library | Narrow window × genre × recency exclusion | `eligible=0 widened=True` in the log; widen the window or wait out the recency list |
| "4 lights" but you have 8 | Config-shape regression | §10.4; the smoke guard should have caught it |

### 15.5 The diagnostic method that actually worked

Recorded because it repeatedly outperformed reasoning from first principles:

1. **Make the code narrate.** When behaviour contradicts the model, add logging that describes what the code *observes*, not what it decides. The satellite's `idle` state and the MA position-snapshot semantics were both discovered this way, and both were invisible to reasoning.
2. **Ask for unfiltered logs.** The `contextlib` crash hid for three releases behind greps that couldn't match it.
3. **Verify the code is running before debugging its logic.** Three consecutive correct fixes were strangled by one missing import.
4. **Check the artifact, not the source.** "It's fixed" and "the fix shipped" are different claims — hence the content-verification step in packaging.
5. **Trust hardware over unit tests for anything involving devices.** Every device bug here (clock skew, asyncio GC, stuck-state naming, queue accumulation) surfaced only on real hardware.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Pool** | The enriched, cached snapshot of the user's library (`library_pool.json`) |
| **Enrichment** | Adding year, popularity and genres to a raw library track |
| **Trust gate** | Minimum `YearConfidence` a song must have to enter a game |
| **`global_score`** | 0–100 worldwide fame, comparable across libraries |
| **`popularity_percentile`** | Rank within this pool, 0–1 |
| **Window** | The percentile range implied by "Top P%" |
| **Widening** | Falling back to the most-popular scored songs when a window is short |
| **Related-genre fill** | Filling from adjacent genres inside the same window, before widening |
| **Pre-start hook** | Our callback fired from `start_round()` on the LOBBY→first-round transition |
| **Split-brain game** | A game whose services (TTS/lights) belong to a previous game |
| **Kick** | The watchdog's `media_play` call to un-stick a device |
| **Off-by-one** | The class of bug where a setting applies to the *next* game |
| **Gate (release)** | compile + import check + both test suites, run before packaging |

---

## Appendix A — Release history in brief

Full annotated changelog: `custom_components/beatify/library/version.py`.

| Range | Theme |
|---|---|
| 0.1.0 – 0.3.1 | Engine foundations: library sampling, worldwide popularity, external years authoritative |
| 0.4.0 – 0.4.2 | Full game integration, admin UI, first upstream rebase (4.2.0-rc9) |
| 0.5.0 – 0.5.7 | Wizard integration, AI curation, playlist management; first hardware feedback round; precise popularity slider; repeat avoidance |
| 0.6.0 – 0.6.3 | Genres, pool durability, real statistics, hybrid fame floor, additive-scan fix |
| 0.7.0 – 0.7.4 | Compilation-year correctness, verified popularity, genre chain (MA→MB→Deezer) |
| 0.7.5 – 0.7.8 | Server-shared then server-authoritative settings; graceful widening |
| 0.7.9 – 0.7.11 | The songs off-by-one (two takes); live match preview; `UpdateLobbyView` |
| 0.7.12 – 0.7.13 | Related-genre fallback; low-match warning; volume mitigation |
| 0.7.14 – 0.7.19 | The config-lag saga: resume watchdog v1, create-time resets, Start-time push, server-side re-apply, the `contextlib` NameError, the config-shape crash |
| 0.7.20 – 0.7.23 | Watchdog GC fix + `enqueue: replace`; narrating watchdog; verified idle trigger; clock-skew counter fix |

## Appendix B — File-change checklist for rebasing

Print this and tick it off (details in §7):

```
[ ] const.py                       PROVIDER_MA_LIBRARY, URI_PATTERN_MA_LIBRARY
[ ] __init__.py                    8 library views + UpdateLobbyView + build_library_pool service
[ ] server/views.py                aggregator re-export of UpdateLobbyView   ← rebase-fragile
[ ] server/library_views.py        new file (endpoints + both Stores)
[ ] server/game_views.py           library create path, _generate_library_songs,
                                   _parse_library_config, pre_start_hook injection,
                                   UpdateLobbyView, _apply_tts_config, _apply_party_lights_config
[ ] game/state_setup.py            replace_songs(); _tts_service/_party_lights resets
[ ] game/state_lifecycle.py        pre_start_hook firing; resume watchdog (+ task retention)
[ ] game/playlist.py               uri_ma_library branch                     ← rebase-fragile
[ ] game/serializers.py            server_now_ms
[ ] services/media_player.py       ma_library capability/URI map, name fallback,
                                   enqueue=replace, pre-play volume re-assert
[ ] library/                       whole package (no upstream counterpart)
[ ] www/admin.html                 mount points, provider chip, CSS link
[ ] www/js/admin.js                library config in create payload; Start push; skew countdown
[ ] www/js/admin/sections/         library.js, library-ai.js (new); media-players.js,
                                   game-settings.js (pushes)
[ ] www/css/library.css            new file
[ ] www/i18n/{en,de}.json          admin.library.* + wizard keys
[ ] www/sw.js                      cache suffix bump
[ ] rebuild bundles + run the gate + hardware smoke test
```

---

*Document generated at v0.7.23. If you change behaviour, change this document in the same commit — the value of this file is entirely in its accuracy.*
