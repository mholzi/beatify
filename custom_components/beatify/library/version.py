"""Beatify library-sourced playlist provider — version & changelog.

Semantic versioning (https://semver.org). Pre-1.0: the engine logic is complete
and unit-tested; integration wiring status is tracked in the changelog. A
release is "integration-complete" (-> 1.0.0) once a game has been played
end-to-end on real hardware.

CHANGELOG
---------
0.9.3  The pool stops blocking the event loop on the way to the first song.
       - Sampling a game's songs ran ENTIRELY on the event loop, twice per
         game: once at create, once from the pre-start hook that fires on the
         host's "Start" tap. Nothing else could run — no WebSocket frame, no
         game timer, no unrelated Home Assistant automation — and it sat
         directly in front of the first play_song, whose budget #2682 already
         measured at 14.6 s of 15.
       - Three changes, measured on an 18k-song / 10.5 MB pool:
         * generate_playlist is pure, so it moved to async_add_executor_job.
         * The parsed pool is cached under hass.data, keyed by the file's
           mtime and size, so the pre-start load is a dict lookup instead of
           an 11 MB json.loads. Any write — scan checkpoint, refresh, host
           correction — changes the key and the next load re-reads. The cache
           is dropped again after 15 idle minutes; a Pi should not hold the
           library in RAM between parties.
         * The dedupe key (NFKD + two regex passes, previously run twice per
           song per game) is precomputed at build time and stored on the
           entry as `_norm_key`. Entries written before this simply lack the
           field and are computed on the fly, so no rescan is needed and
           POOL_SCHEMA_VERSION stays at 1. An identity correction drops the
           stale key; so does a scan that refreshes an entry's artist/title.
       - generate_playlist: 38.2 ms -> 3.8 ms on that pool (and 32.7 ms on a
         pre-0.9.3 pool, from precompiling the two regexes). Event-loop time
         on the generate path: ~73 ms x2 -> 0.
       - +14 checks (test_library_pool_cache.py).

0.9.2  Players flag, the host fixes — no more reports about private libraries.
       - A player tapping "Wrong year?" on a Crate Digger song was still
         taking the public path: appending to the shared data-quality file
         AND opening a GitHub issue about a track the maintainer has never
         seen and cannot check. Worse than useless.
       - Why not simply give players the correction dialog: the correction
         endpoints are admin-authenticated (a guest's request would 401), and
         a party guest silently rewriting the household's library metadata is
         a surprising amount of power. But guests DO notice wrong years
         first, so the signal is worth keeping — only its destination was
         wrong.
       - Players now FLAG the song for the host: handle_report_data detects a
         library song and records {count, reporters} in memory instead of
         reporting, bounded so a long party cannot accumulate flags without
         limit. Flagged-but-unfixed songs sort to the top of the panel's
         Recently played list with an amber marker, so the host fixes what a
         human in the room actually noticed.
       - The button now says what it does, per role: "Wrong year? Fix it"
         (host, own library), "Wrong year? Tell the host" -> "✓ Flagged for
         the host" (player, own library), and the unchanged "Wrong year?"
         report for curated playlists. Four strings x five locales.
       - +6 checks (32 correction checks; 1772 total), one asserting the
         library branch returns BEFORE the GitHub-issue machinery.

0.9.1  "Wrong year?" at reveal now corrects instead of reporting.
       - 0.9.0 shipped the correction dialog but only the PANEL route worked.
         The reveal button still filed a report to the playlist author, which
         for a library song reaches someone who has never seen that track.
       - Cause: the library URI travelled in `admin_song`, which the
         serializer populates during PLAYING only. The REVEAL payload uses a
         different block that deliberately strips URIs so players never
         receive playable identifiers — so the reveal screen had nothing to
         correct with, and the button silently fell through to reporting.
       - Fix keeps upstream's rule intact: the reveal payload now carries a
         BOOLEAN `is_library` and still no URI. The correction endpoints
         resolve the pool entry from title+artist server-side, disambiguated
         against the recently-played list (which does hold URIs, server-side)
         when a library has several entries with the same name.
       - The reveal button opens the dialog for the HOST on a library song
         and reports as before for everyone else. The dialog now ships in the
         player bundle too, because the reveal screen lives there — it is
         inert for players, and the endpoints are admin-authenticated
         regardless. The admin spectator view gained the same affordance at
         reveal (it previously appeared during PLAYING only).
       - +5 checks (26 correction checks; 1766 total), including one that
         asserts the reveal payload still withholds URIs.

0.9.0  Song corrections: fix a wrong year in YOUR pool, from either side.
       - A Crate Digger game is played against the host's own metadata, so
         "Wrong year?" reporting it to whoever published a playlist makes no
         sense. The report button now opens a correction dialog instead, and
         the same dialog is reachable afterwards from a "Recently played"
         list in the panel — the moment you notice differs per host, the work
         is identical.
       - FULL correction, not just the year. The dialog searches MusicBrainz
         and lists candidate recordings with their years, albums and artists,
         so the host can see WHAT was matched. Picking one applies its year;
         if the candidate's title/artist differ, the identity is corrected
         too. The artist/title fields are editable and re-searchable, which
         is how a misidentified track is fixed rather than merely re-dated.
         A manual year entry covers what MusicBrainz doesn't know.
       - Corrections outrank automation: new YearConfidence.USER_VERIFIED (5)
         sits above EXTERNAL_PRIMARY, so a corrected song always passes even
         the strictest year gate, and both the refresh pass and enrichment
         skip locked entries — a rescan can no longer undo the host's work.
         An identity correction invalidates the genres and popularity that
         were derived from the WRONG identity, so the next pass re-fetches
         them for the right song while leaving the human year alone.
       - Original tags are kept (original_title / original_artist): the file
         on disk still carries them, and a later scan must recognise the same
         track.
       - New endpoints: POST library-pool/lookup (candidates + current
         state), POST library-pool/correct (apply), GET library-pool/recent
         (what recent games played, with per-song correction state). The
         library URI reaches the reveal screen through the ADMIN-only song
         payload — the player payload still strips URIs.
       - +21 pure checks (tests/unit/test_library_corrections.py; 1761
         total). 26 UI strings translated across all five locales.

0.8.7  The round clock now starts with the music, not with the round.
       - Reported: at 15s the announcements leave under 7 seconds of song,
         and 30/45s are badly off too — worse in other languages. Estimating
         the announcement cost (0.7.29) could never fix this properly: one
         guess cannot fit every round length, language and device.
       - Upstream already solved the identical problem for intro splashes
         (#1699): stamp a placeholder deadline, report is_deadline_passed()
         False while pending, and recompute the deadline when the deferred
         song actually plays. This applies that pattern to announcements —
         RoundManager gains defer_deadline() and start_timer_at_playback(),
         and the round defers while TTS is configured, then re-stamps once
         playback is confirmed after the announcement chain. Clients are
         notified so their counters restart from the corrected value.
         Every round now gives its configured duration OF MUSIC; the manual
         "Timer delay" (#1211) is no longer needed, though it still works as
         an override for device chimes we cannot observe.
       - VOLUME RATCHET GUARD: on a ShieldTV feeding an AV receiver, MA's
         announcement duck/restore wrote back a slightly HIGHER level every
         round, growing painfully loud within a few rounds. Beatify never
         changes volume there, but it is positioned to notice: the watchdog
         now snapshots volume_level before the announcements and restores it
         once if it has risen by >0.05 during the announcement window. Fires
         at most once per round and only in that window, so the host's own
         volume buttons keep working.
       - PR-NOTES-FOR-MHOLZI.md gains the full write-up of both, plus the
         five missing translation keys, each as a self-contained proposal.
       - +7 checks (56 in the library suites; 1740 total).

0.8.6  Announcement window reserved at enqueue; five upstream i18n gaps.
       - Hardware logs showed the resume watchdog working (kick 1 resumes the
         music) but its ANTICIPATORY kick never firing — no "announcement
         window over" line in a single round. Cause: _announce_busy_until was
         set when a phrase actually began speaking, but everything that asks
         "is the speaker still announcing?" runs immediately after the
         announcements are FIRED — the watchdog arms, the deadline is
         computed, the song-end poll starts. All of them read zero. The
         window is now reserved at enqueue and released again if a phrase is
         dropped as stale, so the anticipatory path can do the work and the
         observational 2-idle-poll path becomes the fallback it was meant to
         be. Expect the post-announcement gap to shrink further.
       - Five keys referenced in code and markup exist in NO locale file:
         admin.ttsPreRoundDelay(+Help), onboarding.startAnywayTitle(+Confirm)
         and playlistHub.topTabs.label. Non-English hosts silently saw the
         English fallbacks — visible as console warnings when switching
         languages. Added and translated in all five locales. This is an
         upstream gap, not ours; worth a separate small PR.
       - +2 checks (49 in the library suites; 1733 total).

0.8.5  ROOT CAUSE of "Cannot start": the provider was never whitelisted.
       - Diagnosis by network trace, not by reading: POST /beatify/api/
         start-game returned 400 in ~4ms with ZERO server log lines. That
         timing ruled out every guard I had been patching — the rejection
         happened before any logging.
       - `_validate_provider()` coerces any provider outside its whitelist to
         PROVIDER_DEFAULT, and `ma_library` was missing from that tuple. So
         the selection silently became Spotify BEFORE the playlist guard ran;
         0.8.4's exemption compared against a value that no longer existed,
         and every earlier fix in this chain was equally unreachable. The
         function's own docstring records the identical failure for Apple
         Music (#808) — the list is a single point of truth that must be
         updated when a provider is added.
       - Players now advertise `supports_ma_library`, so the wizard can grey
         the mode out on speakers that can't serve it (non-MA platforms)
         instead of offering a mode that would fail at playback.
       - Added the missing `errors.INVALID_REQUEST` string the console was
         warning about, in all five locales.
       - +3 checks, two of them real unit tests of _validate_provider
         (47 in the library suites; 1731 total).

0.8.4  "Cannot start — No playlists selected": the create guard.
       - The room was created and the summary line was right, but Start was
         rejected by the SERVER: create_game returns 400 "No playlists
         selected" before reaching the library branch that generates them.
         The message came back from the API and was rendered in the inline
         banner above Start, which is why it looked like a client problem.
       - The guard now exempts `ma_library` only; every other provider still
         requires a selection, and a library game whose generation yields no
         songs is still rejected — an unplayable room must fail loudly.
       - This is the FOURTH place encoding "every game selects a playlist":
         wizard chrome (0.8.1), setup-complete flag and home summary (0.8.2 /
         0.8.3), and now the create guard. Worth stating plainly in the PR:
         adding a generating provider touches all four, and a reviewer should
         expect them.
       - +4 checks (44 in the library suites; 1728 total).

0.8.3  "no playlist" persisted: 0.8.2 read the wrong key.
       - The fix was correct in shape and wrong in detail. Both the wizard
         and the admin page persist the chosen provider under `provider`;
         `selectedProvider` is only the IN-MEMORY name on adminState. 0.8.2
         checked the in-memory name against the persisted blob, so it never
         matched and the home view still summarised a Crate Digger setup as
         "no playlist".
       - Server (`_is_setup_complete`) and client (`isConfigured`, home meta)
         now accept either key, so a half-migrated blob cannot misreport.
       - The unit tests now assert the PERSISTED key, with the alias covered
         separately — 0.8.2's tests passed while the feature was broken
         because they encoded my assumption rather than the format on disk.

0.8.2  "You haven't set up yet" after completing the wizard.
       - Setup completeness required a non-empty playlist selection, in two
         places: `_is_setup_complete()` on the server (#1663's setup blob)
         and the client-side `isConfigured()` fallback. Crate Digger
         GENERATES its playlist from the host's own library at game start and
         therefore never selects one, so a fully configured host was told to
         start setup, and the home view summarised the game as "no playlist".
       - Both now treat `selectedProvider == ma_library` as complete once a
         speaker is chosen, and the home line reads "your library" instead of
         "no playlist" (translated in all five locales).
       - +4 checks, three of them real unit tests of the server predicate
         rather than source guards (39 in the library suites; 1719 total).

0.8.1  Wizard step 3: navigation restored, and the mode says what it plays.
       - Back/Continue vanished on the library step. Not JavaScript: upstream
         drops the whole CTA band with a CSS rule whenever frame 3 is shown
         (`.wiz-frame-playlist:not([hidden]) ~ .wiz-cta`), because the
         Playlist Hub renders its own Back/Continue inside itself. Crate
         Digger replaces the hub and has no such chrome, so the step was left
         with no navigation. The rebase had dropped the `body.wiz-lib-step`
         flag our CSS override keys on; wizard.js sets it again on the
         library step and clears it on every other frame.
       - The provider entry now carries a second line — "Your personal Music
         Assistant library" — in smaller, muted type beneath the name, since
         "Crate Digger" alone doesn't tell a new host whose music this is.
         Translated in all five locales.
       - +3 regression guards (35 in the library suites; 1719 total).

0.8.0  Rebased onto upstream Beatify 4.2.0; the mode is now "Crate Digger".
       - Full rebase from the 4.2.0-rc9 base onto the 4.2.0 stable tag. All
         touchpoints re-applied against upstream's current code rather than
         merged: the pre-start hook now lives in _start_round_locked (#1697
         moved the round body under a lock, which is a safer home for it),
         and replace_songs now calls upstream's own _build_playlist_manager,
         so ramp-up ordering (#1726) survives song regeneration for free.
       - Upstream's suites pass on the rebased tree: 1623 Python unit tests
         and 584 frontend tests, with npm run build:check clean. Three
         regressions were caught and fixed during the port, all of which
         would have shipped: five undefined names (ruff), a None passed
         where the config parser expected a dict (7 upstream tests), and the
         pre-play volume re-assert, which broke 12 upstream media-player
         tests and was DROPPED — it added a state read and a service call
         inside play_song and never demonstrably fixed the volume spike it
         was written for.
       - Our 86 standalone checks became 93 pytest tests under tests/unit/:
         generator selection behaviour, the metadata layer (compilation
         detection, MB year selection, popularity scaling, backup/restore),
         and a regression file where every guard documents the hardware bug
         it prevents. Library package coverage: backup 83%, generator 70%,
         year_resolver 57%. ma_client/pool/matcher remain untested (network
         I/O) — the obvious next contribution.
       - Naming: user-facing Crate Digger becomes "Crate Digger"; the
         internal provider id stays `ma_library`, so a rename is a string
         change. Translations updated across all five locales (en/de full,
         es/fr/nl partially translated with English fallbacks per upstream's
         parity convention).
       - Attribution: engine by DMW.

0.7.31 False auto-advance: an announcement is not a song ending.
       - Report: rounds auto-advanced with REVEAL auto-advance switched
         "Off". The setting was applied correctly — upstream's semantics for
         Off (#1012) are "advance when the SONG ends", not "never advance".
       - The song-end poll decides that by checking the player is no longer
         'playing'. TTS interrupts the track, and devices that don't auto-
         resume (MA voice satellites) then sit in 'idle' with the track
         still loaded — so a reveal announcement read as a finished song and
         the game jumped to the next round a few seconds into REVEAL,
         indistinguishable from the setting being ignored. The logged
         "REVEAL auto-advance (timer=0s, 8s elapsed)" was four 2s polls
         after the interruption.
       - The poll is now announcement-aware: a non-playing state does not
         count as song-end while an announcement is in flight, nor during a
         6s resume grace after it — exactly the window in which the resume
         watchdog is kicking the device. Genuine song endings are unaffected,
         and the existing hard cap still guarantees a game can never stall.
       - Note for anyone reading the UI: "Off" means song-end advance. A
         true "manual only" mode would be a new option, not a bug fix.
       - +2 pure checks (20) and +1 smoke guard (38).

0.7.30 Closing the 3-4s silence between "…3, 2, 1, go" and the music.
       - The gap was never the pre-play interlock: playback is started
         BEFORE the announcements are fired (play at start_round, announce
         two steps later), so every announcement interrupts the song and the
         device must resume. The watchdog then spent 3 seconds PROVING that
         (three consecutive idle polls) before kicking — which is precisely
         the measured gap ("go" at 59s, music at 55s).
       - The watchdog now ANTICIPATES: it waits out the estimated
           announcement window, then kicks IMMEDIATELY if the speaker isn't
         playing, rather than re-confirming what we already expect. Logged as
         "Resume watchdog: announcement window over, resuming immediately".
         Devices that resume on their own (ShieldTV) are untouched — the
         poll loop stays armed as a safety net either way.
       - Fallback kick threshold lowered 3 -> 2 idle ticks now that it only
         handles cases the anticipatory kick misses. Two consecutive remains
         the floor because satellites flap idle<->playing for SINGLE ticks
         during healthy playback.
       - +2 pure checks (18).

0.7.29 Follow-ups to the announcement queue: a regression I caused, plus
       the timer finally accounting for announcements.
       - REGRESSION FIX (0.7.28, mine): with full vocalisation the end-of-
         round announcement stopped playing entirely. The staleness check
         keyed on round AND phase, but reveal / "nobody got it" / time's-up
         phrases are fired exactly AS the phase changes PLAYING -> REVEAL —
         so they were always "stale" by the time they reached the front of
         the queue and were dropped every time. Staleness now keys on the
         ROUND only: a phase change within a round is normal, only a NEW
         round makes a pending phrase wrong.
       - Timer vs announcements: the deadline started counting before the
         round-start announcements played, so a 60s round reached the music
         with ~49s left. The deadline is now shifted by the ESTIMATED cost
         of the announcements that are actually enabled, built from the very
         phrases that will be spoken (new estimate_round_start_announcements).
         This is what #1211's "Timer delay" asks the user to guess, derived
         automatically; a user-set Timer delay still applies on top as the
         manual override for device overhead we cannot see (chimes,
         attention tones). Logged as "+N.Ns deadline for round-start
         announcements".
       - Dead air after "…3, 2, 1, go" trimmed: the pre-play interlock now
         waits 80% of the estimate, overlapping MA's track buffering with
         the tail of the announcement instead of starting after it.
       - +4 pure checks (16).

0.7.28 TTS announcement backlog: out-of-order phrases AND skipped songs
       (one root cause, both TTS-only).
       - User report: with TTS on, a round would skip its song, and phrases
         arrived scrambled — "time's up" playing AFTER the next round had
         started, followed by that round's "3, 2, 1, go".
       - Cause: announcements were pure fire-and-forget. `_tts_announce`
         spawned a task per phrase and `speak()` called tts.speak with
         blocking=False, so Beatify considered an announcement finished the
         moment the service call returned. Music Assistant queues
         announcements per player, so on a slow device the AUDIO ran behind
         the game: the previous round's "time's up" was still queued when
         the next round began, and playback started while the device was
         draining that queue — so play_song's verification window watched an
         announcement instead of the track, timed out, and the song was
         dropped. Exactly why it only ever happened with TTS enabled.
       - Fix, two halves: (1) announcements now queue behind each other
         using an estimated speech duration, and one that is no longer
         relevant when it reaches the front is DROPPED rather than played
         late — a "time's up" from a finished round is worse than silence;
         (2) round start waits (bounded at 8s) for the speaker to finish
         announcing before starting playback, via the new
         announcement_busy_seconds().
       - Both halves are provider-neutral and belong upstream: the backlog
         affects every provider, and satellites make it visible.
       - +12 pure checks (tests/test_tts_queue.py) and +2 smoke guards (37).

0.7.27 Unranked songs could reach ANY popularity window (real bug).
       - The unknown-popularity fill was gated on `hi >= 0.66`, but a
         "Top P%" window is [1-P/100, 1.0] — `hi` is ALWAYS 1.0, so the
         guard passed for every window including Top 1%. Whenever the window
         couldn't fill (narrow window + genre filter + recency exclusion),
         games were topped up with songs that have NO popularity data at all.
         Reported: "Ce reve bleu" (a French Aladdin dub,
         popularity_percentile=null) in a Top 1% round — it was never scored,
         so it was never "famous"; it was filler.
         The gate now tests `lo <= 0.34`: unranked songs are only acceptable
         when the request itself reaches into the obscure end. Narrow windows
         now return FEWER songs rather than wrong ones.
       - +3 pure checks (12) and +1 smoke guard (35).

0.7.26 Backup & restore for the enriched pool (user request).
       - The pool is the one expensive artifact this integration produces —
         hours of rate-limited MusicBrainz and Deezer calls — and until now
         it was protected only by whatever backs up /config. The library
         panel gains "Download backup" and "Restore from backup…".
       - GET /beatify/api/library-pool/backup streams a gzipped bundle
         containing the pool AND the library settings, so restoring on a
         fresh install brings back the configuration too. Compression runs
         in an executor (a big pool would otherwise stall the event loop).
       - POST /beatify/api/library-pool/restore takes ?mode=replace|merge.
         MERGE unions two pools by track URI and is what makes this more
         than insurance: scan on one machine, fold the result into another,
         or recover a damaged pool without losing newer work. The winner per
         URI is chosen by year confidence, then popularity, then genres, so
         a merge can only IMPROVE an entry — never trade a verified year for
         a tag year because the other file was newer.
       - Safety: the current pool is copied to library_pool.pre-restore-
         <timestamp>.json before anything is written; uploads are capped
         both compressed (128 MB) and decompressed (512 MB) against gzip
         bombs; merged pools are re-finalized so percentiles are recomputed
         rather than carried over stale; a bundle from a DIFFERENT Music
         Assistant server is accepted but reported, since its URIs may not
         resolve. A hand-copied bare library_pool.json is accepted too.
       - +16 pure checks (tests/test_backup_restore.py) and +6 smoke guards
         (34). Reference documentation updated (new module, endpoints,
         invariants).

0.7.25 Upstream 4.2.0 compatibility pass (analysed against the stable tag).
       - Reset semantics: 4.2.0 (#2036) made force-reset installation-wide,
         clearing the server-side setup blob so "reset means reset". Our
         game_output_settings Store was invisible to that cleanup, so the
         pre-start hook would have re-applied the PRE-reset device/TTS/
         lights to the next game — silently contradicting the reset. The
         reset path now clears our Store too (any later push repopulates
         it). Correct on the current base as well.
       - Pre-warm race: 4.2.0 (#1540) pre-warms the MediaPlayerService
         during LOBBY, scheduled at create with the OLD entity. A pre-warm
         completing AFTER our device switch nulls the cached service could
         reinstate a service bound to the previous speaker. The update
         endpoint and the pre-start re-apply now cancel (and re-schedule)
         the pre-warm via upstream's own helpers; getattr-guarded, so this
         is a no-op on bases without them.
       - Verified that NONE of our provider-neutral fixes were fixed by
         4.2.0: create_game still leaves _tts_service/_party_lights stale,
         music_assistant.play_media still ships no enqueue mode, there is
         still no announce-resume handling, no clock-skew correction on the
         round counter, and no pre-play volume re-assert. PR notes updated;
         the asset-fingerprint suggestion was dropped (4.2.0 fixed it).
       - +3 smoke guards (28).

0.7.24 Handoff reference documentation (no behaviour change).
       - Adds MY-LIBRARY-PROVIDER-REFERENCE.md: a complete technical
         reference covering the architecture, every module of the library
         package, data schemas, the HTTP API, an exhaustive list of the
         modifications made to upstream files, the design decisions and
         their rationale, the root cause of every bug fixed during hardware
         testing, the device-quirk matrix, testing/release discipline, an
         upstreaming guide with a suggested two-PR split, known limitations
         and open items, and a diagnostics cookbook. Written so the project
         can be continued (or upstreamed) without reverse-engineering.
       - Corrects a stale comment in generator.py whose example values
         predated the current absolute-floor formula (40 + 30*lo): top-5%
         is floor 68.5, not ~62.

0.7.23 The phantom early time-up: client clock skew on the round counter.
       - "Counter showed 20s remaining when the server said time's up":
         the admin countdown derives remaining time from the server's
         absolute deadline against the CLIENT device's clock — a device
         ~20s off shows exactly that much phantom time at the true expiry.
         (Upstream's own serializer comment acknowledges this hazard for
         the title/artist vote window and mitigates it there; the round
         counter never got the same treatment.) The server ran rounds at
         full length the whole time — the display lied.
       - Fix mirrors the vote-window approach: the state payload now stamps
         server_now_ms; the admin countdown computes the skew once per
         state receive and corrects every tick. Device clocks no longer
         matter. (Upstream-worthy; the player-view counter likely shares
         the hazard — report if observed and it gets the same one-liner.)
       - Reminder shipped alongside: the audible-music window still shrinks
         by the announcement chain unless the TTS "Timer delay" (#1211)
         setting is used (~12s; ~18 with countdown announcements enabled).
       - +2 smoke guards (25).

0.7.22 Resume watchdog: hardware-verified triggers (idle-stuck satellites).
       - The narrating build captured both signatures. VA satellites stick
         in state='idle' after an announcement — HA never reports 'paused'
         even while MA's UI shows the paused track (user-confirmed). The
         watchdog now kicks on sustained idle (>=3s) with a loaded title,
         alongside plain 'paused'.
       - The frozen-position stall heuristic FALSE-POSITIVED: MA entities
         report media_position as snapshot+timestamp (HA derives the live
         position), so a frozen pos with periodic updated_at refreshes is
         HEALTHY playback — the ShieldTV rounds it "kicked" three times
         were playing fine. Heuristic removed; 'playing' is trusted.
       - Narration stays (state+title per tick) for this verification
         round; will be demoted to debug once satellites confirm.

0.7.21 Narrating resume watchdog + stall detection (satellite diagnosis).
       - v0.7.20's watchdog armed and polled correctly but never observed
         'paused' — while the satellite audibly sat paused. HA's state for
         the MA player entity evidently reports something else during the
         stuck condition. The watchdog now LOGS every observation
         ("Resume watchdog[NN]: state=... pos=... updated=... title=...")
         so one round on a satellite produces the full state signature, and
         it kicks on BOTH known signatures: explicit 'paused', and
         'playing' with media_position frozen across 3 consecutive polls
         (MA believing it resumed while the device didn't follow). Kick
         outcomes and exit reasons are logged too.

0.7.20 Satellite resume + ShieldTV time-travel: the last two playback bugs.
       - The resume watchdog NEVER RAN: asyncio.create_task() without a
         retained reference — Python's documented weak-ref footgun let the
         task be garbage-collected before executing (zero watchdog lines
         despite the arm condition holding). The task is now stored on the
         game state (previous one cancelled, cleaned up via done-callback),
         logs "TTS resume watchdog armed" at round start, tolerates
         transient 'idle' states, and exits only on 'off'/timeout/3 kicks.
       - ShieldTV returning to PREVIOUS songs (sometimes mid-round): the MA
         play_media call sent no enqueue mode, so prior rounds accumulated
         in Music Assistant's queue — after a TTS interrupt the queue resume
         could advance into stale entries. Every round now sends
         enqueue=replace: the queue contains exactly the current song, so a
         resume can only resume THAT song. (Both upstream-worthy; noted for
         the PR.)
       - +2 smoke guards (23).

0.7.19 Config-shape fix: the dict-as-entity-id crash (tts.py:81) and the
       phantom "4 lights".
       - With the contextlib import fixed, the logs exposed the next layer:
         configure_tts takes the TTS ENTITY ID as its first positional
         argument (+ unpacked announce_* keywords), and
         configure_party_lights takes (entity_ids, intensity, mode, presets)
         — but the update endpoint and pre-start hook passed the RAW CONFIG
         DICTS. Python accepted them silently: TTS then crashed every
         announcement at hass.states.get(<dict>) (the tts.py:81 frames), and
         party lights iterated the dict's KEYS as entity ids — the logged
         "Party Lights started: 4 lights, intensity=medium" was four config
         keys masquerading as lights, after which every phase change failed
         against nonexistent entities.
       - New shared appliers (_apply_tts_config/_apply_party_lights_config)
         unpack exactly like the create endpoint (enabled flag honored,
         entity extraction, announce_* forwarding, pre-round delay), disable
         on falsy/invalid, and serve both the update endpoint and the
         pre-start hook — one source of truth.
       - Smoke suite: +3 guards banning raw-dict configure_* calls (21).

0.7.18 THE missing import — one NameError strangled three correct fixes.
       - The user's log capture showed the smoking frame: game_views.py
         line 789 raising inside the update endpoint, right after the
         media_player apply. Cause: `with contextlib.suppress(...)` with NO
         module-level `import contextlib` — a v0.7.14 conditional insert
         checked "is 'import contextlib' in the file", matched a LOCAL
         aliased import inside an unrelated function, and skipped adding
         the real one. Every request then died mid-handler: media player
         applied (hence music moving devices), TTS/lights never configured,
         nothing persisted to the Store, and the pre-start re-apply found
         an empty store — all three architectural fixes were correct and
         all three were strangled by this one line.
       - Fixed with the module-level import. The healthy sequence now:
         "Lobby updated: media_player" -> "Lobby/game updated: tts ..." ->
         (persist) -> at Start "Pre-start: tts configured/disabled" etc.;
         and with a TTS service finally attached on the reset path, the
         resume watchdog arms and logs "resuming playback (kick N)" on the
         satellites.
       - Smoke suite gains a bare-module-name guard (uses of contextlib.*
         etc. require a module-level import) — the 6th shipped-NameError
         class is now mechanically checked.

0.7.17 Reset-path configs fixed via server-side re-apply; resume watchdog
       rewritten (real bug found).
       - UPSTREAM CODE ANALYSIS (pristine clone) explained the reset
         asymmetry: force-reset WIPES all Beatify localStorage (including
         beatify_tts / beatify_party_lights), reloads, and the home view
         auto-creates a room — a create racing wiped-then-rewritten storage
         plus a token reset that can 401 the client's config push. The
         results-screen path is a clean create, hence it worked.
       - Fix mirrors the songs architecture: device/TTS/lights pushes are
         now PERSISTED in the HA Store, and the pre-start hook re-applies
         them SERVER-SIDE at every first-round start — whatever was last
         saved wins on every path, reset included. INFO logs "Pre-start:
         tts configured/disabled", "Pre-start: media_player -> X".
       - Resume watchdog v1 had a genuine bug: it early-returned when the
         player wasn't paused at the first check — but at that moment the
         ANNOUNCEMENT is still playing, so it always quit before the pause
         occurred (hardware: every satellite round stayed paused).
         Rewritten: polls up to ~20s, kicks whenever paused is observed
         (up to 3, logged as "resuming playback (kick N)").
       - Upstream cross-check: pristine HEAD (4.2.0-rc13) is ahead of our
         base, so raw diffs mostly show upstream's own progress; our
         touchpoints remain the known module set, each smoke-guarded
         (17 checks). Full rebase onto current upstream stays a PR-prep
         roadmap item.

0.7.16 TTS/lights lag finally closed: configs pushed at the Start press.
       - The user's clarification cracked it: TTS/lights are only editable
         OUTSIDE a game, and the lobby's reset button creates the next room
         IMMEDIATELY — with the settings of that moment. Toggles changed
         afterwards never reached the room (the v0.7.14 saveGameSettings
         hook isn't in those toggles' save path, and the server has no
         store of these configs to regenerate from, unlike songs).
       - startGameplay() now pushes the CURRENT device/TTS/lights configs
         through the update endpoint right before the phase flip, awaited so
         configure_*/disable_* land before the first announcement. Combined
         with v0.7.15's create-time resets and explicit-disable semantics,
         there is no remaining path for a config to lag: born clean, updated
         at start, disable honored mid-game.

0.7.15 Stale TTS/lights services fixed at the root (the split-brain game).
       - Observed: new game on the VA satellite with TTS DISABLED — music on
         the satellite, announcements STILL on the previous game's ShieldTV.
         Mechanism: create_game nulls _media_player_service (with upstream's
         own comment explaining the recycling trap) but NOT _tts_service /
         _party_lights; with TTS disabled, configure_tts is never called, so
         the previous game's service (enabled + bound to the old device)
         survives wholesale. create_game now applies the identical reset to
         both; the previous game's end path still handles output restore.
       - The update endpoint gains explicit-disable semantics: a present-but-
         falsy tts/party_lights now tears the service down mid-game
         (disable_tts / disable_party_lights) instead of being skipped — so
         toggling TTS off applies to the RUNNING game too.
       - Both findings added to PR-NOTES-FOR-MHOLZI.md (the reset gap is an
         upstream bug affecting every provider).

0.7.14 TTS satellite playback fixed (resume watchdog); settings changes
       apply to the RUNNING game (device mid-game, TTS, party lights).
       - CRITICAL fix: round announcements interrupt the just-started song;
         MA voice satellites fail the auto-resume and sit "paused" until a
         human presses play (music never audible with TTS on). A watchdog
         now verifies playback ~2.5s after the announcement chain and
         presses play on the device's behalf (retries once; WARNING-logged).
         ShieldTV resumed fine on its own — platform-dependent behavior.
       - The "second 3-2-1-GO" on ShieldTV is upstream's separate OPT-IN
         countdown announcement chained after the round-start one — the
         satellite's broken resume swallowed it, the Shield plays both.
         Disable "countdown" in TTS settings if one announcement is enough.
       - The update endpoint now accepts mid-game changes: media_player in
         PLAYING/REVEAL too (applies from the next round; the v0.7.11
         version was LOBBY-only by design — the report was a mid-game
         switch), plus tts and party_lights configs applied through
         upstream's own configure_* methods. Saving game settings pushes all
         three to the active game (server no-ops when none).

0.7.13 Volume-scare mitigation + the low-match warning actually turns red.
       - Round-start full-volume spike: NOT caused by the library provider —
         upstream's play path contains no volume logic at all (set_volume
         serves only the host buttons and the #1516 end-of-game restore).
         The spike originates below Beatify: devices/MA starting a new
         stream at their own default level, or (if TTS announcements are on)
         MA's announce-duck restore landing ~1s after the song starts.
         Mitigation shipped: play_song now re-asserts the HA-known volume
         immediately BEFORE every stream start — a no-op on well-behaved
         players, closes the gap on devices that reset per stream.
         (Upstream-worthy; added to the PR notes pile.)
       - The low-match warning's red color was losing a CSS specificity
         fight against the base hint-text rule (bold won because the base
         sets no font-weight). Now properly red.

0.7.12 Related-genre fallback (user-designed) + low-match warning.
       - When "Top N% of <genre>" can't fill a game, songs from ADJACENT
         genres inside the SAME popularity window now fill first — "Top 5%
         Trance" (18 eligible on the reporter's 51k pool) fills with top-5%
         House/Dance/Electro/Techno instead of the most famous mis-tagged
         songs deep in the Trance tag (label pollution floats famous pop to
         the top of any tag it leaks into: Michael Jackson in a Trance
         game). Curated adjacency map for ~35 coarse genres; percentile
         widening and unknown-fill remain as later fallbacks. Rock at Top 5%
         (299 eligible) confirmed the architecture — no fallback triggers
         when supply suffices.
       - The match counter turns RED + bold with a warning when fewer songs
         match than the game needs; the "Last game generated" row shows
         "+ related: House, Dance" when the fallback fired; the generate log
         gains expanded=[...].
       - +9 pure checks (related map, fill preference, expansion reporting,
         no-expansion-when-plenty).

0.7.11 Output-device switching applies to the CURRENT lobby (same
       off-by-one class as songs); creation-freeze audit.
       - Rooms freeze their parameters at creation. Confirmed lagging:
         media_player — switching output devices only took effect one game
         later, because the lazily-built MediaPlayerService recycles the
         entity captured at construction (upstream documents this exact
         mechanism in create_game's reset comment). New endpoint
         POST /beatify/api/game/update-lobby applies a device change to a
         LOBBY-phase game (validates entity + platform support, nulls the
         cached media service); the speaker picker fires it on every
         selection (server no-ops when no lobby exists).
       - AUDIT of other creation-frozen parameters: songs (fixed in 0.7.10
         via the pre-start hook), popularity/genres/size/gate (server-
         authoritative Store since 0.7.6). Still creation-frozen and
         POTENTIALLY lagging if changed while a lobby exists: round
         duration, language, TTS/party-lights config, bonus toggles, saved-
         playlist selection — the update-lobby endpoint is built extensible
         for these; report any you can reproduce and it lands next.
       - Infra: container reset lost the repo (restored from the v0.7.10
         artifact); tools/check_imports.py rebuilt (immediately caught a
         missing aggregator re-export of the new view — a boot-blocker) and
         a smoke suite (runtime imports + source guards for every shipped
         bug class) re-established. tools/ and tests/ now SHIP IN THE ZIP so
         resets can't destroy the safety net again.

0.7.10 Off-by-one, take two: regeneration moved to the start_round
       chokepoint (the websocket start path bypassed v0.7.9's fix).
       - v0.7.9 hooked regeneration into the REST /start-gameplay view — but
         the host UI starts games via the WEBSOCKET admin handler, which
         calls game_state.start_round() directly. Hardware evidence: a
         four-game chain still shifted by exactly one (Synth-Pop game played
         the Jazz selection, Classical played Synth-Pop, Dance played
         Classical).
       - The fix now lives where EVERY path must pass: start_round() awaits
         an optional pre_start_hook once, on the LOBBY -> first-round
         transition. The create endpoint injects the hook for generated
         library games; it regenerates via replace_songs() with the
         server-stored settings, fires once, never blocks the game on
         failure, and leaves saved-playlist/other-provider games untouched.
       - +4 source-guard checks (162).

0.7.9  THE off-by-one fixed: songs regenerate at gameplay start. Top 1%
       slider. Live "N songs match" counter.
       - Root cause of "each game plays the previous game's selection":
         songs are attached to the game at room CREATION and the Start
         button on an existing lobby only flips LOBBY->PLAYING — so settings
         changed after room creation applied to the NEXT game (observed
         perfectly: a "Rock" game full of synth pop, the following no-genre
         game full of rock). Library games now REGENERATE their songs inside
         start-gameplay with the current server-stored settings, via a new
         GameState.replace_songs() that mirrors rematch's manager rebuild
         (#1377 total_rounds derivation included). Phase is guaranteed LOBBY
         there; saved-playlist games are untouched.
       - Popularity slider now reaches Top 1%% (step 1) — for newbie-friendly
         games with only the most famous songs.
       - Live counter under the slider: "{n} songs match these settings",
         updating as you drag/toggle (new preview endpoint; the pure
         count_eligible mirrors the generator's filters and is parity-tested
         against generate's own eligible count).
       - +2 checks (158).

0.7.8  Graceful window widening — "Top 5% Jazz" can no longer flood with
       obscure film cues.
       - Root cause of the genre-game reports: a narrow popularity window
         intersected with a genre chip often leaves < 30 eligible songs, and
         the old fallback filled the game with UNKNOWN-popularity songs of
         that genre — which in a soundtrack-heavy library means film cues
         (Deezer/MB tag Morricone/Delerue/Goldsmith albums as Jazz/Electro/
         Classical). The Synth Pop game worked precisely because ~175 tagged
         songs x top-5%% sufficed without fill.
       - Now the window widens DOWNWARD through SCORED songs instead: "Top 5%%
         Jazz" degrades to "the most popular Jazz you own" (Ella first, cues
         last), never to random obscurities. Unknown-popularity songs are a
         last resort only when even the widened scored pool can't fill a
         game. The "Last game generated" row and the log line show
         "expanded to best available" / widened=True when it happens.
       - Genre labels remain coarse/album-level (some pollution like a pop
         band tagged "Modern Classical" is inherent to the sources).
       - +5 checks (156): widening fills to size from next-most-popular,
         flag semantics, unknowns still excluded when scored songs suffice.

0.7.7  Self-diagnosing panel: "Last game generated" row (no logs needed).
       - The log-based verification kept vanishing because logger.set_level
         is runtime-only and resets on every HA restart — after the v0.7.6
         install+restart, four correctly-generated games logged invisibly
         and looked like "something doesn't work at all".
       - The panel's stats card now shows what the last game ACTUALLY used:
         "Top 5% · Rock · 87 → 30 (21:34)" — settings, eligible count,
         chosen count, time. When saved playlists were selected instead, it
         says so explicitly ("2 saved playlist(s) — settings not applied").
         Recorded in hass.data at generate/skip time, served via the status
         payload, visible on every device.
       - Import discipline note: the DOMAIN reference in the recorder was
         caught missing by the runtime import check before shipping (5th
         save of this class).

0.7.6  Server-AUTHORITATIVE settings at game start + generation-trigger logs.
       - v0.7.5 synced settings between open panels but games started from
         the LOBBY (which never mounts the panel) still sent that device's
         defaults — observed: a "Rock" setup generating with genres=None.
         The server now reads the stored settings ITSELF at game start;
         the client payload is only a fallback for keys the Store lacks.
         Stale browsers, cached JS, unhydrated pages: all irrelevant now.
       - "No new generate line" is never a mystery again: the server logs
         both triggers — "no playlists selected -> generating fresh songs"
         and "N saved playlist(s) selected -> playing those (popularity/
         genre settings do not apply to saved playlists)". A second game
         with no new line means the room reused its songs (start a fresh
         game from the lobby for a new mix).
       - +6 checks (151): merge precedence (stored wins, per-key fallback)
         and source-level guards on the game_views implementation.

0.7.5  Server-shared game settings (the "slider/genres ignored" mystery) +
       genre chips stay visible during scans.
       - ROOT CAUSE FOUND via the generate log: settings lived in per-browser
         localStorage. A game started from another PC (or fresh session)
         silently used THAT device's defaults — observed as pop=5+Dance on
         one machine and pop=50/no-genres on another, flip-flopping between
         games. The engine obeyed exactly what each device sent.
       - Library settings (popularity %, songs/game, year gate, scan size,
         genre selection) are now stored SERVER-SIDE via HA's Store helper
         (GET/POST /beatify/api/library-settings). The panel loads them on
         open (server wins over local) and saves on every change (debounced),
         so every device sees and uses the same values.
       - Genre chips + stats stay rendered DURING scans — an active genre
         filter can never be invisible again (a hidden stale 'Dance' chip
         silently filtered games while a scan hid the chip row).
       - +6 checks (145): settings sanitizer (clamps, gate whitelist, genre
         cap, garbage tolerance).

0.7.4  Genres from MusicBrainz + Deezer (MA's library has none — measured).
       - The v0.7.3 diagnostic settled it: 20,000 MA detail fetches -> 0
         genres, 0 errors. MA's library metadata is genre-empty for
         Plex-synced tracks, so MA can never fill the chips. Genres now come
         from a chain: MA (kept for setups where it works) -> MusicBrainz
         recording tags (FREE — parsed from the same responses we already
         fetch for years, merged by community vote across confident
         recordings) -> Deezer album genres (coarse Pop/Rock/Dance labels,
         fetched only when MB tags were empty and the verified rank match
         yielded an album id).
       - Wired into BOTH paths: new-track enrichment and the refresh pass —
         so the pending v3 overnight refresh fixes years AND fills genres in
         one run. The runtime smoke test asserts refreshed entries carry
         genres.
       - Fixed a would-be import-time NameError (nonexistent timeout
         constants) caught by real-import testing before shipping.
       - +7 checks (139): MB tag extraction gates (score/artist), Deezer
         album-genre parsing, smoke-test genre assertions.

0.7.3  Dash-reversed title candidates, genre retry with visible diagnostics.
       - YEARS: "Main Title - Scarface" kept its wrong 2022 year through the
         refresh because hard-clean keeps the LEFT dash side ("Main Title" —
         generic, unfindable). MB queries now try up to three candidates:
         cleaned title, hard-cleaned core, and the RIGHT side of a " - "
         split. _RESOLVER_V bumped to 3, so "Improve existing songs"
         reappears and one more overnight pass re-resolves the backlog with
         the better candidates.
       - GENRES: pool dump showed genres_checked=19,000 with 0 genres — the
         detail-fetch ran everywhere and MA returned nothing, but the
         diagnostic summary was invisible (INFO suppressed by default).
         The genres_checked flag is now VERSIONED (True==v1 -> retried once
         at v2), summaries log at WARNING when zero genres return, and pool
         entries store item_id/provider for robust future fetches. The next
         scan retries the 19k backfill (LAN-fast) and its summary line will
         be visible in the default HA log.
       - +6 checks (132): candidate ordering/dedup incl. the Scarface case.

0.7.2  HOTFIX: refresh crashed on a second closure-scoped name; runtime
       smoke test added so this class of bug can't ship again.
       - The extracted async_refresh_pool referenced _finalize, a closure
         local to async_build_pool (same class as the _CHECKPOINT_BATCH
         NameError it crashed on at your hands). _finalize is now a shared
         module-level finalize_pool(); the refresh writes carry the existing
         pool's scan metadata over (built_at/library_total/etc.).
       - _CHECKPOINT_BATCH promoted to module level (the v0.7.1 hardware
         crash at pool.py:588).
       - NEW: a runtime smoke test that actually EXECUTES async_refresh_pool
         with mocked network/writes — including the checkpoint branch — is
         part of the permanent suite (126 checks). It caught the _finalize
         bug before shipping; static checks (py_compile, import graph)
         cannot see closure-scope leaks, only execution can.
       - Genre fetch now logs a per-scan summary ("Genre fetch summary:
         N jobs -> M with genres (K via album), X no-genres, Y errors") and
         falls back to ALBUM-level genres when tracks carry none — the next
         scan's log line diagnoses why your pool shows 0 genre tags.
       - scandir loop-warning: warm_asset_fingerprint() now recomputes
         unconditionally in the executor every 3s AND the serve-path TTL was
         raised to 60s, so the event loop can never hit the recompute branch
         even if a warm cycle is delayed.

0.7.1  HOTFIX + refresh-as-separate-job + UX.
       - FIX crash "name 'asyncio' is not defined": ma_client.py used asyncio
         (Semaphore/gather) in the new detail-genre/probe/sampling code but
         never imported it, so every v0.7.0 scan failed immediately. Imported.
       - Refresh is now a SEPARATE background job ("Improve existing songs"),
         not folded into a scan — a 1,000-song 20-minute scan is no longer
         silently turned into a multi-hour refresh. New endpoint
         /beatify/api/library-pool/refresh; status reports a backlog count and
         its own progress; can run alongside a scan.
       - UX: scan/Rescan button moved next to "Songs to prepare"; refresh row
         (backlog + button) added below year accuracy.
       - scandir loop-warning: the asset-fingerprint cache has a 5s TTL, so a
         single boot-time warm-up wasn't enough — it's now re-primed off-loop
         every 4s, so the HTML serve path always hits the cached fast branch.
       - +4 checks (121): refresh backlog accounting.

0.7.0  Correct years for compilation tracks, verified popularity, real
       genres, and scans without full-library reads (P1-P3 + year fix).
       - YEARS: the MB query quotes the title as an exact phrase, so
         compilation-decorated titles ("(Re-Recorded)", "Scarface - Main
         Title") matched only reissue-registered recordings -> reissue years
         (Flashdance->2001, Scarface->2022, Rain Man->2010 on hardware).
         New hard-clean FALLBACK query (all trailing (...)/[...] groups and
         " - tail" stripped) + result window 10->25. NOT a regression — the
         flaw predates and became visible once popular songs surfaced.
       - POPULARITY: Deezer lookup now scans top-5 results and accepts only a
         VERIFIED artist+title match (strict title equality after version-
         word trim; "Cold" can no longer inherit "Cold Heart"'s rank — the
         top-5%%-shows-obscure-songs mechanism).
       - ONE-TIME REFRESH PASS: on the next scan, existing entries get years
         re-resolved (v2 resolver) and popularity re-verified, checkpointed;
         MB throttle makes this hours for a 16k pool — runs in background,
         progress shown, only once (entries are version-flagged).
       - GENRES (P1): MA list models carry no genre metadata; genres now come
         from per-track DETAIL fetches (LAN, concurrent) for new tracks and
         are backfilled for cached ones (flagged, one-time).
       - SCANS (P3): target-size scans no longer read all ~300k tracks first.
         Library size is PROBED (~2*log2 N one-item calls) and new candidates
         come from RANDOM page sampling. "Entire library" scans still read
         everything (that's the point there).
       - +14 checks (117): verified-match accept/reject incl. the Cold/Cold
         Heart hard rejection, hard_clean_title, split_library_uri.

0.6.3  FIX additive scans: cached tracks no longer re-enter enrichment.
       - A "1,000-song scan" iterated 16,000 (all cached + new): counts, ETA,
         and time were all wrong. Cached entries now get a fast in-memory
         basic-field refresh (title/artist/album/genres — keeps future genre
         backfill working) and only genuinely NEW tracks are enriched and
         counted. Log line reports both numbers.
       - Diagnosed (fix designs in HANDOFF-OPUS.md): genres are absent from
         MA LIST responses (detail fetch needed, P1); "top 5%" quality needs
         the wrong-Deezer-match check (P2, diagnostic included); full
         enumeration per scan to be replaced by random-page sampling (P3).

0.6.2  Hybrid fame floor, UX polish round, scandir silenced, handoff docs.
       - Narrow popularity windows now ALSO require absolute real-world fame
         (floor scales with the window: top-5% -> ~68). Fixes "top 5% of a
         soundtrack-heavy pool is still obscure cues": percentile says "top of
         THIS pool", the floor says "actually famous". Tested.
       - Step-3 cards swapped: Game settings on top (used every game), library
         scan below (occasional). Provider version now shown INSIDE the panel
         (footer patching dropped — less upstream chrome touched).
       - Scan ETA is phase-aware and cumulative (sliding window mixed
         enumerate/enrich phases and jittered wildly).
       - Once-per-boot blocking-scandir warning silenced by priming upstream's
         asset fingerprint in the executor at setup (upstream-suggested too).
       - Docs: PR-NOTES-FOR-MHOLZI.md (change reasoning + upstream
         suggestions) and HANDOFF-OPUS.md (state, verification list, gotchas).

0.6.1  HOTFIX: v0.6.0 failed to load (bad ENGINE_VERSION import).
       - library_views.py imported ENGINE_VERSION from version.py, which only
         exports __version__ — so Beatify wouldn't set up at all. Fixed to
         `from .version import __version__ as ENGINE_VERSION` (matching pool.py).
       - Root of why it slipped through: tools/check_imports.py skipped
         ABSOLUTE intra-package imports (custom_components.beatify.X) and only
         checked relative ones; the broken line used the absolute form. The
         checker now resolves absolute intra-package imports too (and is
         stricter about CONSTANT/dunder names behind a lazy __getattr__),
         and is verified to catch this exact regression.

0.6.0  Genres, pool durability, real stats, inverted slider, observability.
       - ROOT CAUSE of the shrinking pool found and fixed: pool writes were a
         plain write_text — an HA restart mid-write truncated the JSON and the
         next scan silently rebuilt from zero (25k -> 10k on real hardware).
         Writes are now atomic (tmp + fsync + os.replace) and the previous
         good pool is kept as .json.bak; the loader recovers from it.
       - GENRE selection: genres are captured from MA metadata (Plex/Jellyfin
         tags) at scan time, backfilled onto cached songs by the next cheap
         rescan, surfaced as toggle chips (top 24 with counts), and filter
         generation (any-match, case-insensitive). Empty selection = all.
       - Library stats panel: library total, prepared, verified per gate,
         popularity/genre coverage, last-scan time.
       - Popularity slider INVERTED per feedback: right = biggest hits.
       - Step 3 split into two cards: "Your library" (scan/stats/gates) and
         "Game settings" (popularity, size, genres).
       - Wizard-chosen library settings now persist across reloads (they were
         session-only — a likely contributor to "slider does nothing").
       - Observability: every generation logs size/pop%/window/genres/
         eligible/chosen to the HA log, so setting-vs-effect mismatches are
         diagnosable from logs.
       - Footer shows "· Crate Digger vX.Y.Z" so installs are visually
         verifiable (user request).
       - +7 checks (102 total).

0.5.7  Precise popularity slider, real year-floor fix, repeat avoidance.
       - Popularity is now a 0-100% "draw from the most popular P%" SLIDER,
         not three coarse bands. P maps to a percentile window [1-P/100, 1];
         "top 10%" on the user's library = ~1,140 genuinely-popular songs
         (was: all 3 options drew from the same ~10,600 "mainstream" blob).
       - Unknown-popularity songs (no Deezer data — mostly the obscure old
         stuff) are now EXCLUDED from a narrow/popular window; they only fill
         a wide/obscure window. This is why "Popular" kept surfacing 1930s
         oddities.
       - REAL year-floor fix: the guess slider's min was hard-coded min="1950"
         in player.html (not YEAR_MIN as 0.5.6 assumed). Now 1900, so pre-1950
         songs are guessable. (YEAR_MIN stays 1900 for server validation.)
       - Repeat avoidance: a 400-URI ring buffer of recently-played songs is
         excluded from new library games (ignored if it would starve a game).
       - +5 checks (95 total) covering the window, unknown-exclusion, and the
         recent-play exclusion.

0.5.6  Difficulty slider actually works + pre-1950 years + Echo wake.
       - FIX the popularity banding: absolute Deezer-rank thresholds put ~93%
         of a real 18.5k-song library into "mainstream" (10613/705/83), so the
         slider did nothing. Banding is now PERCENTILE-based within the user's
         own library — verified to split that same library 3801/3800/3800.
         Existing pools are re-banded from stored percentiles at generate time
         (NO rescan needed); raw ranks were already saved.
       - YEAR_MIN 1950 -> 1900 so pre-1950 library songs (1920s-40s) are
         guessable; matches the resolver's plausibility floor.
       - Start-game wakes an idle media player (Echo drops to 'unavailable'
         when napping) and re-checks for ~3s before failing.
       - +7 checks incl. an end-to-end proof the slider separates popular from
         obscure on the bug's own condition (all songs absolutely-mainstream).

0.5.5  HOTFIX: restore the ma_library branch in game.playlist.get_song_uri.
       - The branch that returns uri_ma_library was dropped during an upstream
         rebase (mholzi rewrote get_song_uri several times for the Amazon
         #1361 and storefront work). Result: EVERY generated song was skipped
         ("no URI for provider 'ma_library'"), the game found zero playable
         songs, and start-game 500'd -> "Network error" in the UI. Found on
         the user's first real game start (18,527-song verified pool).
       - Added an end-to-end guard test that feeds a generator entry through
         get_song_uri, so a future rebase dropping this branch fails CI.
       - Also aligned the scan-subset tests with the current "target = NEW
         tracks added on top of cached" semantics (rescans grow the pool).

0.5.4  Library CSS moved to its own stylesheet (cache-proof + PR-clean).
       - All feature CSS now lives in css/library.css(.min), linked by
         admin.html next to styles.min.css. A new URL cannot be served stale
         by any pre-feature service-worker or HTTP cache — on hardware, stale
         styles.min.css kept hiding the step-3 CTA and panel styling even
         while fresh JS ran (mixed old/new assets).
       - Bonus: upstream's styles.css is untouched again, keeping the
         eventual PR diff clean. sw.js precaches the new file; cache suffix
         bumped to -mylib4.

0.5.3  Service-worker cache bust + enumeration feedback.
       - sw.js CACHE_VERSION gets a fork suffix so stale pre-update caches can
         never be served again (user saw F5 alternating old/new UI — classic
         stale-SW symptom despite upstream's fingerprint mechanism).
       - Reading a 300k+ library out of Music Assistant takes minutes before
         enrichment starts; that phase now reports progress ("Reading your
         library… N songs found") instead of sitting on "Starting scan…".

0.5.2  First on-hardware feedback round (huge-library support + step-3 UX).
       - FIX: Back/Continue missing on library step 3 — an upstream CSS rule
         hides the CTA band whenever frame 3 is visible (the hub brings its
         own). wizard.js now flags library-mode step 3 on <body> and CSS
         restores the band.
       - Huge libraries (found on a 317k-track Plex): the 50k enumeration cap
         is gone, and scans now prepare a TARGET-SIZE subset (new "Songs to
         prepare" select: 1k/2.5k/5k/10k/25k/all) — already-enriched tracks
         are always kept, so each rescan extends the pool. MusicBrainz's
         ~1 req/s throttle makes full 300k+ scans multi-day; the panel says
         so and shows a live rate-based ETA.
       - UX: familiarity slider replaced with a "Song popularity" select
         (Popular / Mixed / Obscure) — fixes the jumping label and the
         orphaned legend line; clearer wording per user feedback.
       - Panel/modal controls now fully self-styled (lib-btn / lib-input),
         independent of upstream utility classes.
       - +6 unit checks for the pure subset selection (80 total).

0.5.1  HOTFIX: DeleteUserPlaylistView import error on HA startup.
       - The root __init__ imports views via the server/views.py aggregator;
         the new delete view was defined in playlist_views.py but never
         re-exported there, so Beatify failed to load ("cannot import name
         'DeleteUserPlaylistView'"). Re-exported alongside SavePlaylistView.
       - Added tools/check_imports.py: AST import-graph verification that
         catches wrong-module imports without a HA install (py_compile
         cannot); proven to flag exactly this bug. Found on the user's HAOS
         2026.7.1 first boot of v0.5.0.

0.5.0  Wizard-integrated setup, playlist management, and AI curation.
       - FIX lobby loop: BeatifyHome.isConfigured() required selected
         playlists, so a finished ma_library setup bounced back to "Start
         setup" forever. Library mode now counts as configured.
       - Wizard step 3 for ma_library is now the library panel (familiarity /
         songs-per-game / year-accuracy, all editable) with the scan running
         server-side in the background while setup continues. Existing pools
         (scans are global, one per server) are presented with stats and a
         "Rescan" action instead of forcing a re-scan. Hub remains step 3 for
         streaming providers. resumeAtStep returns 3 again.
       - Pool file moved OUT of the playlists tree
         (beatify/library_pool.json) so it can't surface as a broken
         playlist in the hub. No migration needed (no pools in the wild).
       - Game start with ma_library + selected playlists now plays those
         files; a fresh mix is generated only when nothing is selected.
       - Playlist management: shared user-playlist writer; save-a-fresh-mix
         endpoint (POST /beatify/api/library-playlists/generate); strict
         user-playlist delete (POST /beatify/api/playlists/user/delete) with
         an on-card ✕ in the hub for files under playlists/user/.
       - AI curation (BYO model, matching the #1052 generator trust model):
         GET /beatify/api/library-pool/export (artist/title/year/fame only),
         POST /beatify/api/library-playlists/resolve (picks -> verified
         years + playable URIs, unmatched reported per row), and a modal in
         the admin library panel (copy prompt -> paste answer -> preview ->
         save). Pure matcher module, unit-tested.
       - library.js rewritten as a root-scoped factory: one panel
         implementation mounted in both the admin settings and wizard step 3,
         instances synced through adminState. EN + DE strings throughout.
       - Tests: 74 python checks (+9 matcher), 410 vitest (+8: AI helpers,
         wizard resume revert). parseAiAnswer bare-array bug caught by its
         own new test and fixed before shipping.

0.4.2  Wizard: skip the playlist step for the library provider.
       - The first-run wizard marched provider -> playlist hub for every
         provider; ma_library generates playlists from the library, so the
         playlist step is meaningless. Now step 2 -> 4 (and back 4 -> 2), and
         resumeAtStep() returns 4 for ma_library instead of 3.
       - Found during first real-hardware test (HAOS 2026.7, MA 2.9.5).
       - +1 unit test (402 total).

0.4.1  Rebase onto current upstream main (db91033, manifest 4.2.0-rc9).
       - Zero drift in touched files; upstream's new shared provider
         whitelist (#1675) reuses game_views._validate_provider, so
         ma_library is now accepted by the mix endpoint validation too.
       - All JS bundles + CSS rebuilt on the new tree (upstream vitest
         suite: 401/401 passing). Verified against MA models 1.1.151
         (MA 2.9.x): all Track fields the client reads are unchanged.

0.4.0  Full game integration + admin UI. The provider is now playable
       end-to-end (pending hardware verification):
       - Playback: ma_library registered in PLATFORM_CAPABILITIES and
         _PROVIDER_URI_FIELDS; name+artist fallback in
         _play_via_music_assistant when a stored library URI fails.
       - Game start: /beatify/api/start-game accepts provider "ma_library"
         and samples songs from the pool (library.size / .difficulty /
         .year_gate in the request body; year gates strict|balanced|tags_ok).
       - New endpoints: GET /beatify/api/library-pool (status + stats),
         POST /beatify/api/library-pool/build (background scan w/ progress).
       - HA service beatify.build_library_pool + services.yaml (automations,
         e.g. nightly refresh).
       - Admin UI: Crate Digger provider chip (gated on Music Assistant
         speakers via supports_ma_library), settings panel with worldwide
         familiarity slider, songs-per-game, year-accuracy select, and a
         scan button with live progress. Wizard lists the provider too.
       - i18n: English + German strings.
       - manifest: music_assistant added to after_dependencies.

0.3.1  Standalone-testability fix (no behavior change).
       - Package __init__ now imports HA-dependent modules (pool, ma_client)
         lazily via PEP 562 __getattr__, so the pure logic imports without
         Home Assistant installed.
       - Test suite loads the pure modules by file path; runs from any cwd with
         `python3 tests/test_library_logic.py` (no PYTHONPATH, no HA).

0.3.0  External sources made authoritative for release years.
       - Year confidence reworked into a 5-tier scale: EXTERNAL_PRIMARY
         (MusicBrainz, verified) > EXTERNAL_SECONDARY (Deezer year) > TAG_STUDIO
         > TAG_COMPILATION > NONE. Default game gate is now EXTERNAL_PRIMARY:
         tag years are excluded from games unless the gate is explicitly relaxed.
       - MusicBrainz matching hardened: filter by match score (>=90) AND verify
         the artist credit, then take earliest plausible release among confident
         matches (fixes cross-artist date leaks, e.g. cover vs. original).
       - Title cleaning strips version suffixes before MB lookup.
       - Added optional Deezer release-year fallback (year_fallback build flag).

0.2.0  Worldwide popularity for the difficulty slider (fairness fix).
       - Popularity normalized onto an absolute 0..100 global-fame scale and
         banded on that absolute value (absolute_band), instead of percentiles
         relative to the host's own library.
       - Confirmed from MA source that metadata.popularity is worldwide (set
         only from streaming providers; Plex/Jellyfin/filesystem never set it).
       - MA client rewritten to use the live MusicAssistantClient
         (config_entry.runtime_data.mass) instead of the HA get_library action,
         which trims away year/album_type/popularity. Verified vs MA 2.8.8.
       - AlbumType handling aligned to real values (live/soundtrack untrusted);
         album-name compilation heuristic added for metadata-light ItemMappings.

0.1.0  Initial engine: library-sourced playlist generation.
       - Inverts the curated-playlist model (generate from the user's own
         library via Music Assistant) so "missing songs" is impossible.
       - year_resolver, popularity, generator, ma_client, pool modules.
       - Beatify-schema output via uri_ma_library; const.py + playlist.py wired.
"""

__version__ = "0.9.3"
__author__ = "DMW"
__mode_name__ = "Crate Digger"

# Schema version of the cached pool JSON on disk. Bump only when the pool file
# format changes in a way that requires a rebuild.
POOL_SCHEMA_VERSION = 1
