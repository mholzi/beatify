"""Library pool writers must not overwrite each other (#3156).

A scan used to keep its initial snapshot and rewrite the whole pool at every
checkpoint, so a correction or restore saved mid-scan was silently undone.
Every writer now goes through ``async_update_pool`` (one lock, re-read before
write) and scan/refresh checkpoints merge into the pool on disk.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.beatify.library import corrections, pool as pool_mod

from .test_library_pool_cache import FakeHass, make_entry, write_pool


@pytest.fixture
def hass(tmp_path):
    return FakeHass(tmp_path)


def _read(hass):
    return {
        s["uri_ma_library"]: s
        for s in json.loads(pool_mod.pool_path(hass).read_text("utf-8"))["songs"]
    }


def _cached(i, **over):
    return make_entry(i, genres=["Rock"], genres_checked=2, popularity_raw=50, **over)


def _track(i):
    return {
        "uri": f"library://track/{i}",
        "title": f"New {i}",
        "artist": f"New Artist {i}",
        "album": "A",
        "genres": ["Pop"],
        "ma_popularity": 40,
    }


async def _correct(hass, uri, year):
    def _apply(pool):
        songs = pool["songs"]
        for i, s in enumerate(songs):
            if s["uri_ma_library"] == uri:
                songs[i] = corrections.apply_correction(s, year=year)
        return pool

    await pool_mod.async_update_pool(hass, _apply)


def _patch_scan(monkeypatch, hass, new_tracks, on_enrich):
    monkeypatch.setattr(pool_mod, "_CHECKPOINT_BATCH", 1)
    monkeypatch.setattr(pool_mod, "find_ma_config_entry_ids", lambda _h: ["e1"])
    monkeypatch.setattr(pool_mod, "_get_session", lambda _h: object())

    async def sample(_h, _e, _seen, _n, progress_cb=None):
        return list(new_tracks), 100

    async def mb(_s, _a, title, _t):
        await on_enrich(title)
        return 1999, []

    async def genres(*_a, **_k):
        return {}

    monkeypatch.setattr(pool_mod, "async_fetch_track_genres", genres)
    monkeypatch.setattr(pool_mod, "async_sample_new_tracks", sample)
    monkeypatch.setattr(pool_mod, "async_musicbrainz_year_genres", mb)


async def _scan(hass):
    return await pool_mod.async_build_pool(hass, target_size=10)


class TestScanVersusCorrection:
    async def test_correction_during_scan_survives_checkpoints(self, hass, monkeypatch):
        write_pool(hass, [_cached(0, year=1980, year_confidence=3)])
        corrected = False

        async def on_enrich(title):
            nonlocal corrected
            # The host corrects the cached song and the first new song while
            # the scan is mid-flight (after checkpoint 1, before checkpoint 2).
            if title == "New 2" and not corrected:
                corrected = True
                await _correct(hass, "library://track/0", 1971)
                await _correct(hass, "library://track/1", 1962)

        _patch_scan(monkeypatch, hass, [_track(1), _track(2)], on_enrich)
        await _scan(hass)

        songs = _read(hass)
        assert set(songs) == {f"library://track/{i}" for i in range(3)}
        assert songs["library://track/0"]["year"] == 1971
        assert songs["library://track/0"]["user_corrected"] is True
        # Added by checkpoint 1, corrected, then must not be replaced by the
        # scan's own copy at checkpoint 2.
        assert songs["library://track/1"]["year"] == 1962
        assert songs["library://track/1"]["year_source"] == "user"
        assert songs["library://track/2"]["year"] == 1999

    async def test_identity_correction_survives_scan_refresh_of_cached_entry(
        self, hass, monkeypatch
    ):
        write_pool(hass, [_cached(0)])
        cached_track = {**_track(0), "title": "Song 0", "artist": "Artist 0"}

        async def on_enrich(title):
            if title == "New 1":
                await _correct_identity(hass)

        async def _correct_identity(h):
            def _apply(pool):
                pool["songs"][0] = corrections.apply_correction(
                    pool["songs"][0], title="Fixed Title"
                )
                return pool

            await pool_mod.async_update_pool(h, _apply)

        _patch_scan(monkeypatch, hass, [cached_track, _track(1)], on_enrich)
        await _scan(hass)

        assert _read(hass)["library://track/0"]["title"] == "Fixed Title"


class TestScanVersusRestore:
    async def test_restore_during_scan_is_kept_and_removed_entry_stays_removed(
        self, hass, monkeypatch
    ):
        write_pool(hass, [_cached(0), _cached(5)])

        async def on_enrich(title):
            if title == "New 2":
                # Replace-restore: only entry 9 exists afterwards.
                await pool_mod.async_update_pool(
                    hass,
                    lambda _disk: pool_mod.finalize_pool(
                        {"library://track/9": _cached(9)},
                        built_at=1,
                        config_entry_id=None,
                        library_total=None,
                        target_size=None,
                    ),
                )

        _patch_scan(monkeypatch, hass, [_track(1), _track(2)], on_enrich)
        await _scan(hass)

        songs = _read(hass)
        # restored entry survives; entries the restore dropped are not
        # resurrected from the scan's snapshot; new enrichment is added.
        assert "library://track/9" in songs
        assert "library://track/0" not in songs
        assert "library://track/5" not in songs
        assert "library://track/2" in songs


class TestUpdatePoolLock:
    async def test_concurrent_updates_serialise(self, hass):
        write_pool(hass, [make_entry(0, counter=0)])

        async def bump():
            def _m(pool):
                pool["songs"][0]["counter"] += 1
                return pool

            await pool_mod.async_update_pool(hass, _m)

        # Slow executor: yields so un-locked read-modify-writes would clash.
        orig = hass.async_add_executor_job

        async def slow(target, *args):
            await asyncio.sleep(0)
            return await orig(target, *args)

        hass.async_add_executor_job = slow
        await asyncio.gather(*(bump() for _ in range(10)))
        assert _read(hass)["library://track/0"]["counter"] == 10

    async def test_none_from_mutate_writes_nothing(self, hass):
        path = write_pool(hass, [make_entry(0)])
        before = path.read_text("utf-8")
        assert await pool_mod.async_update_pool(hass, lambda _p: None) is False
        assert path.read_text("utf-8") == before


class TestRefreshVersusCorrection:
    async def test_refresh_checkpoint_does_not_undo_correction(self, hass, monkeypatch):
        write_pool(
            hass,
            [
                make_entry(0, _resolver_v=1, year=1980),
                make_entry(1, _resolver_v=1, year=1981),
            ],
        )
        monkeypatch.setattr(pool_mod, "_CHECKPOINT_BATCH", 1)
        monkeypatch.setattr(pool_mod, "_get_session", lambda _h: object())
        calls = 0

        async def mb(_s, _a, _t, _th):
            nonlocal calls
            calls += 1
            if calls == 2:
                await _correct(hass, "library://track/0", 1955)
            return 2001, []

        async def dz(_s, _a, _t):
            return 10, None

        monkeypatch.setattr(pool_mod, "async_musicbrainz_year_genres", mb)
        monkeypatch.setattr(pool_mod, "async_deezer_rank_album", dz)

        await pool_mod.async_refresh_pool(hass)

        songs = _read(hass)
        assert songs["library://track/0"]["year"] == 1955
        assert songs["library://track/0"]["user_corrected"] is True
        assert songs["library://track/1"]["year"] == 2001


class TestNoMisleadingClaim:
    def test_refresh_docstring_no_longer_claims_last_write_wins(self):
        assert "last-write-wins" not in (pool_mod.async_refresh_pool.__doc__ or "")
