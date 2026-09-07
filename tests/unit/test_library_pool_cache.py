"""Crate Digger — the pool parse and playlist sampling must stay off the loop.

Issue #2694: Crate Digger loaded and re-parsed an ~11 MB pool file and then
sampled a playlist from it on the event loop, twice per game — once at game
creation, once from the pre-start hook on the host's "Start" tap. Nothing
else could run for the duration, and it sat directly in front of the first
play_song.

Three guards live here:

* the dedupe key is stored on the entry at build time (and recomputed for
  pools written before it existed, so an existing install keeps working),
* the parse is cached under ``hass.data`` and re-read when the file changes,
* the generate path uses the executor rather than the loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from custom_components.beatify.library import corrections, pool as pool_mod
from custom_components.beatify.library.generator import (
    NORM_KEY_FIELD,
    _norm_key,
    entry_key,
)

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"


def make_entry(i: int, **over):
    entry = {
        "title": f"Song {i}",
        "artist": f"Artist {i}",
        "uri_ma_library": f"library://track/{i}",
        "year": 1990 + (i % 30),
        "year_confidence": 3,
        "global_score": float(i % 100),
    }
    entry.update(over)
    return entry


class FakeHass:
    """Enough Home Assistant to exercise the pool loader."""

    def __init__(self, root: Path):
        self.data: dict = {}
        self.config = type("C", (), {"path": lambda _s, p: str(root / p)})()
        self.executor_calls = 0

    @property
    def loop(self):
        return asyncio.get_running_loop()

    async def async_add_executor_job(self, target, *args):
        self.executor_calls += 1
        return target(*args)


@pytest.fixture
def hass(tmp_path):
    return FakeHass(tmp_path)


def write_pool(hass, songs):
    path = pool_mod.pool_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"songs": songs}), encoding="utf-8")
    return path


class TestPrecomputedDedupeKey:
    def test_finalize_pool_stores_the_key(self):
        out = pool_mod.finalize_pool(
            {"u": make_entry(1, artist="Björk", title="Jóga (Remastered)")},
            built_at=0,
            config_entry_id=None,
            library_total=1,
            target_size=None,
        )
        assert out["songs"][0][NORM_KEY_FIELD] == _norm_key(
            "Björk", "Jóga (Remastered)"
        )

    def test_finalize_pool_does_not_recompute_an_existing_key(self):
        entry = make_entry(1)
        entry[NORM_KEY_FIELD] = "sentinel|value"
        out = pool_mod.finalize_pool(
            {"u": entry},
            built_at=0,
            config_entry_id=None,
            library_total=1,
            target_size=None,
        )
        assert out["songs"][0][NORM_KEY_FIELD] == "sentinel|value"

    def test_entry_key_falls_back_for_pools_built_before_2694(self):
        """An existing install must not need a rescan to keep working."""
        old = make_entry(1, artist="Motörhead", title="Ace of Spades (Live)")
        assert NORM_KEY_FIELD not in old
        assert entry_key(old) == _norm_key("Motörhead", "Ace of Spades (Live)")

    def test_entry_key_prefers_the_stored_value(self):
        entry = make_entry(1)
        entry[NORM_KEY_FIELD] = "stored|key"
        assert entry_key(entry) == "stored|key"

    def test_identity_correction_drops_the_stale_key(self):
        """The stored key was derived from the wrong name."""
        entry = make_entry(1, artist="Wrong", title="Wrong Title")
        entry[NORM_KEY_FIELD] = _norm_key("Wrong", "Wrong Title")
        fixed = corrections.apply_correction(entry, title="Right Title")
        assert NORM_KEY_FIELD not in fixed
        assert entry_key(fixed) == _norm_key("Wrong", "Right Title")

    def test_year_only_correction_keeps_the_key(self):
        entry = make_entry(1)
        entry[NORM_KEY_FIELD] = "stored|key"
        fixed = corrections.apply_correction(entry, year=1977)
        assert fixed[NORM_KEY_FIELD] == "stored|key"

    def test_prepare_backfills_missing_keys(self):
        pool = {"songs": [make_entry(i) for i in range(5)]}
        pool["songs"][0]["popularity_percentile"] = 0.99
        pool_mod.prepare_pool_for_generate(pool)
        assert all(s[NORM_KEY_FIELD] for s in pool["songs"])
        assert pool["songs"][0]["familiarity_band"] is not None


class TestParsedPoolCache:
    async def test_second_load_reuses_the_parse(self, hass):
        write_pool(hass, [make_entry(i) for i in range(3)])
        first = await pool_mod.async_load_pool_cached(hass)
        second = await pool_mod.async_load_pool_cached(hass)
        assert first is second, "the pre-start hook must not re-parse the pool"

    async def test_a_rewrite_invalidates_the_cache(self, hass):
        path = write_pool(hass, [make_entry(i) for i in range(3)])
        first = await pool_mod.async_load_pool_cached(hass)
        path.write_text(
            json.dumps({"songs": [make_entry(i) for i in range(9)]}), encoding="utf-8"
        )
        second = await pool_mod.async_load_pool_cached(hass)
        assert second is not first
        assert len(second["songs"]) == 9

    async def test_missing_pool_is_not_cached(self, hass):
        assert await pool_mod.async_load_pool_cached(hass) is None

    async def test_load_and_prepare_run_in_the_executor(self, hass):
        write_pool(hass, [make_entry(i) for i in range(3)])
        await pool_mod.async_load_pool_cached(hass)
        assert hass.executor_calls >= 3  # stat, read, prepare

    async def test_cached_pool_is_prepared(self, hass):
        write_pool(hass, [make_entry(i) for i in range(3)])
        cached = await pool_mod.async_load_pool_cached(hass)
        assert all(s[NORM_KEY_FIELD] for s in cached["songs"])


class TestGenerationIsOffTheLoop:
    def test_generate_path_uses_the_executor(self):
        code = (COMPONENT / "library" / "__init__.py").read_text(encoding="utf-8")
        assert "async_add_executor_job" in code, "#2694: generate_playlist is pure"
        assert "async_load_pool_cached" in code

    def test_write_pool_invalidates_the_cache(self):
        code = (COMPONENT / "library" / "pool.py").read_text(encoding="utf-8")
        body = code.split("async def _write_pool", 1)[1]
        assert "invalidate_pool_cache" in body.split("def _get_session", 1)[0]
