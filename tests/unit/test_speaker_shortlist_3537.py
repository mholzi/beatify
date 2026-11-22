"""#3537 - Step 1 shows a short speaker list; the rest stays reachable.

Covers the pure rules in ``services/speaker_shortlist.py`` (duplicate
detection, the short list, the admin's override), the ``duplicate_of`` field
the media-player scan now adds, and the admin-only endpoint that stores the
admin's choice.
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import StreamReader
from aiohttp.test_utils import make_mocked_request

from custom_components.beatify.server import views
from custom_components.beatify.services.media_player import (
    _reset_scan_log_state,
    async_get_media_players,
)
from custom_components.beatify.services.speaker_shortlist import (
    apply_shortlist,
    find_duplicates,
    name_key,
    sanitize_overrides,
)


def _p(entity_id, name, platform, state="idle", **extra):
    return {
        "entity_id": entity_id,
        "friendly_name": name,
        "platform": platform,
        "state": state,
        **extra,
    }


MA_LIVING = _p("media_player.living_room_ma", "Living Room", "music_assistant")
SONOS_LIVING = _p("media_player.living_room", "Living Room Sonos", "sonos")
MA_KITCHEN = _p("media_player.kitchen_ma", "Kitchen", "music_assistant")
ALEXA_KITCHEN = _p("media_player.kitchen_echo", "Kitchen", "alexa_media")


# ---------------------------------------------------------------------------
# name_key
# ---------------------------------------------------------------------------


def test_name_key_drops_integration_words_numbers_and_accents():
    assert name_key("Living Room Sonos") == "living room"
    assert name_key("Living Room (MA)") == "living room"
    assert name_key("Küche 2") == "kuche"
    assert name_key("Sonos") == ""  # nothing left never matches
    assert name_key(None) == ""


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------


def test_same_device_marks_the_native_player_as_duplicate_of_ma():
    meta = {
        MA_LIVING["entity_id"]: {"device_id": "dev1", "area_id": None},
        SONOS_LIVING["entity_id"]: {"device_id": "dev1", "area_id": None},
    }
    dups = find_duplicates([MA_LIVING, SONOS_LIVING], meta)
    assert dups == {SONOS_LIVING["entity_id"]: MA_LIVING["entity_id"]}


def test_same_area_and_same_name_is_a_duplicate():
    meta = {
        MA_KITCHEN["entity_id"]: {"device_id": "a", "area_id": "kitchen"},
        ALEXA_KITCHEN["entity_id"]: {"device_id": "b", "area_id": "kitchen"},
    }
    assert find_duplicates([MA_KITCHEN, ALEXA_KITCHEN], meta) == {
        ALEXA_KITCHEN["entity_id"]: MA_KITCHEN["entity_id"]
    }


def test_ma_is_always_the_one_kept():
    """Never the MA player is marked, whichever comes first in the list."""
    meta = {
        MA_LIVING["entity_id"]: {"device_id": "dev1"},
        SONOS_LIVING["entity_id"]: {"device_id": "dev1"},
    }
    dups = find_duplicates([SONOS_LIVING, MA_LIVING], meta)
    assert MA_LIVING["entity_id"] not in dups
    assert dups[SONOS_LIVING["entity_id"]] == MA_LIVING["entity_id"]


@pytest.mark.parametrize(
    ("native", "native_meta", "ma_meta"),
    [
        # Same area, different speaker name: a TV soundbar next to the Sonos.
        (
            _p("media_player.living_room_tv", "Living Room TV", "sonos"),
            {"device_id": "x", "area_id": "living"},
            {"device_id": "y", "area_id": "living"},
        ),
        # Same name, different area.
        (
            _p("media_player.living_room", "Living Room", "sonos"),
            {"device_id": "x", "area_id": "office"},
            {"device_id": "y", "area_id": "living"},
        ),
        # Same name, no area known at all: not enough to be sure.
        (
            _p("media_player.living_room", "Living Room", "sonos"),
            {"device_id": None, "area_id": None},
            {"device_id": None, "area_id": None},
        ),
    ],
)
def test_conservative_when_unsure(native, native_meta, ma_meta):
    meta = {native["entity_id"]: native_meta, MA_LIVING["entity_id"]: ma_meta}
    assert find_duplicates([MA_LIVING, native], meta) == {}


def test_working_native_player_is_not_hidden_behind_an_unavailable_ma_player():
    ma_down = {**MA_LIVING, "state": "unavailable"}
    meta = {
        MA_LIVING["entity_id"]: {"device_id": "dev1"},
        SONOS_LIVING["entity_id"]: {"device_id": "dev1"},
    }
    assert find_duplicates([ma_down, SONOS_LIVING], meta) == {}


def test_without_music_assistant_nothing_is_a_duplicate():
    sonos2 = _p("media_player.living_room_2", "Living Room", "sonos")
    meta = {
        SONOS_LIVING["entity_id"]: {"device_id": "dev1"},
        sonos2["entity_id"]: {"device_id": "dev1"},
    }
    assert find_duplicates([SONOS_LIVING, sonos2], meta) == {}


def test_browser_targets_are_never_duplicates():
    tv = _p("beatify_browser.tv", "TV screen", "beatify_browser", browser_target="tv")
    meta = {
        tv["entity_id"]: {"device_id": "dev1"},
        MA_LIVING["entity_id"]: {"device_id": "dev1"},
    }
    assert find_duplicates([MA_LIVING, tv], meta) == {}


# ---------------------------------------------------------------------------
# apply_shortlist
# ---------------------------------------------------------------------------


def _by_id(players):
    return {p["entity_id"]: p for p in players}


def test_duplicates_are_left_off_the_short_list():
    dups = {SONOS_LIVING["entity_id"]: MA_LIVING["entity_id"]}
    out = _by_id(apply_shortlist([MA_LIVING, SONOS_LIVING, MA_KITCHEN], dups, {}))
    assert out[MA_LIVING["entity_id"]]["shortlisted"] is True
    assert out[MA_KITCHEN["entity_id"]]["shortlisted"] is True
    sonos = out[SONOS_LIVING["entity_id"]]
    assert sonos["shortlisted"] is False
    assert sonos["duplicate_of"] == MA_LIVING["entity_id"]
    assert sonos["visibility_override"] is None


def test_manual_choice_overrides_the_automatic_rule():
    dups = {SONOS_LIVING["entity_id"]: MA_LIVING["entity_id"]}
    overrides = {
        "shown": [SONOS_LIVING["entity_id"]],
        "hidden": [MA_KITCHEN["entity_id"]],
    }
    out = _by_id(
        apply_shortlist([MA_LIVING, SONOS_LIVING, MA_KITCHEN], dups, overrides)
    )
    assert out[SONOS_LIVING["entity_id"]]["shortlisted"] is True
    assert out[SONOS_LIVING["entity_id"]]["visibility_override"] == "shown"
    assert out[MA_KITCHEN["entity_id"]]["shortlisted"] is False
    assert out[MA_KITCHEN["entity_id"]]["visibility_override"] == "hidden"


def test_selected_speaker_is_never_hidden():
    dups = {SONOS_LIVING["entity_id"]: MA_LIVING["entity_id"]}
    overrides = {"hidden": [MA_KITCHEN["entity_id"]]}
    out = _by_id(
        apply_shortlist(
            [MA_LIVING, SONOS_LIVING, MA_KITCHEN],
            dups,
            overrides,
            pinned=[SONOS_LIVING["entity_id"], MA_KITCHEN["entity_id"]],
        )
    )
    # A duplicate that is the saved pick, and a speaker the admin hid that is
    # the saved pick: both stay on the short list.
    assert out[SONOS_LIVING["entity_id"]]["shortlisted"] is True
    assert out[MA_KITCHEN["entity_id"]]["shortlisted"] is True


def test_browser_targets_pass_through_unchanged():
    tv = _p("beatify_browser.tv", "TV screen", "beatify_browser", browser_target="tv")
    out = apply_shortlist([tv], {}, {"hidden": ["beatify_browser.tv"]})
    assert out == [tv]


def test_apply_shortlist_does_not_mutate_its_input():
    players = [dict(MA_LIVING)]
    apply_shortlist(players, {}, {})
    assert "shortlisted" not in players[0]


# ---------------------------------------------------------------------------
# sanitize_overrides
# ---------------------------------------------------------------------------


def test_sanitize_keeps_valid_ids_once_and_hidden_wins():
    raw = {
        "shown": ["media_player.a", "media_player.a", "media_player.b", 5, "<x>"],
        "hidden": ["media_player.b", "not an id"],
    }
    assert sanitize_overrides(raw) == {
        "shown": ["media_player.a"],
        "hidden": ["media_player.b"],
    }


def test_sanitize_bad_shapes():
    assert sanitize_overrides(None) == {"shown": [], "hidden": []}
    assert sanitize_overrides({"shown": "media_player.a"}) == {
        "shown": [],
        "hidden": [],
    }


# ---------------------------------------------------------------------------
# The media-player scan marks duplicates from the registries
# ---------------------------------------------------------------------------


def _entry(entity_id, platform, unique_id, device_id=None, area_id=None):
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.unique_id = unique_id
    entry.domain = "media_player"
    entry.device_id = device_id
    entry.area_id = area_id
    return entry


def _state(entity_id, name):
    state = MagicMock()
    state.entity_id = entity_id
    state.state = "idle"
    state.attributes = {"friendly_name": name}
    return state


@pytest.fixture(autouse=True)
def _clean_scan_cache():
    _reset_scan_log_state()
    yield
    _reset_scan_log_state()


async def test_scan_marks_native_player_on_the_ma_device_as_duplicate():
    """Different unique_ids (so #1627 keeps both), same device."""
    entries = [
        _entry("media_player.wohnzimmer_2", "music_assistant", "ma-1", "dev1"),
        _entry("media_player.wohnzimmer", "sonos", "RINCON_1", "dev1"),
        _entry("media_player.kueche", "sonos", "RINCON_2", "dev2"),
    ]
    names = {
        "media_player.wohnzimmer_2": "Wohnzimmer",
        "media_player.wohnzimmer": "Wohnzimmer",
        "media_player.kueche": "Küche",
    }
    by_id = {e.entity_id: e for e in entries}
    hass = MagicMock()
    hass.states.async_all = MagicMock(
        return_value=[_state(e.entity_id, names[e.entity_id]) for e in entries]
    )
    registry = MagicMock()
    registry.entities.values = MagicMock(return_value=entries)
    registry.async_get = MagicMock(side_effect=by_id.get)
    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=registry
    ):
        players = await async_get_media_players(hass)

    dup = {p["entity_id"]: p["duplicate_of"] for p in players}
    assert dup == {
        "media_player.wohnzimmer_2": None,
        "media_player.wohnzimmer": "media_player.wohnzimmer_2",
        "media_player.kueche": None,
    }
    json.dumps(players)  # still serialisable for /api/status


async def test_status_shortlist_pins_the_saved_speaker():
    players = [
        {**MA_LIVING, "duplicate_of": None},
        {**SONOS_LIVING, "duplicate_of": MA_LIVING["entity_id"]},
    ]
    with patch.object(
        views, "async_load_speaker_visibility", AsyncMock(return_value={})
    ):
        out = _by_id(
            await views.async_shortlist_players(
                MagicMock(), players, {"last_player": SONOS_LIVING["entity_id"]}
            )
        )
    assert out[SONOS_LIVING["entity_id"]]["shortlisted"] is True
    assert out[SONOS_LIVING["entity_id"]]["duplicate_of"] == MA_LIVING["entity_id"]


# ---------------------------------------------------------------------------
# /beatify/api/speaker-visibility — admin only
# ---------------------------------------------------------------------------


def _post_request(body: bytes, token: str | None):
    reader = StreamReader(
        mock.Mock(_reading_paused=False), 2**16, loop=asyncio.get_event_loop()
    )
    reader.feed_data(body)
    reader.feed_eof()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return make_mocked_request(
        "POST", "/beatify/api/speaker-visibility", headers=headers, payload=reader
    )


def _hass():
    """A hass whose only valid token is 'admin-token'; Companion bypass off."""
    hass = MagicMock()
    hass.data = {}
    hass.auth.async_validate_access_token = MagicMock(
        side_effect=lambda t: MagicMock() if t == "admin-token" else None
    )
    return hass


class TestSpeakerVisibilityView:
    async def test_admin_post_stores_the_sanitised_choice(self):
        view = views.SpeakerVisibilityView(_hass())
        body = json.dumps(
            {"shown": ["media_player.sonos_a"], "hidden": ["media_player.x", "bad"]}
        ).encode()
        with patch.object(views, "async_save_speaker_visibility", AsyncMock()) as save:
            resp = await view.post(_post_request(body, "admin-token"))
        assert resp.status == 200
        save.assert_awaited_once()
        stored = save.await_args.args[1]
        assert stored == {
            "shown": ["media_player.sonos_a"],
            "hidden": ["media_player.x"],
        }

    @pytest.mark.parametrize("token", [None, "guest-or-stale-token"])
    async def test_non_admin_post_is_rejected_and_nothing_is_stored(self, token):
        view = views.SpeakerVisibilityView(_hass())
        body = json.dumps({"hidden": ["media_player.x"]}).encode()
        with patch.object(views, "async_save_speaker_visibility", AsyncMock()) as save:
            resp = await view.post(_post_request(body, token))
        assert resp.status == 401
        save.assert_not_awaited()

    async def test_non_admin_get_is_rejected(self):
        view = views.SpeakerVisibilityView(_hass())
        req = make_mocked_request("GET", "/beatify/api/speaker-visibility")
        resp = await view.get(req)
        assert resp.status == 401

    async def test_admin_get_returns_the_stored_choice(self):
        view = views.SpeakerVisibilityView(_hass())
        req = make_mocked_request(
            "GET",
            "/beatify/api/speaker-visibility",
            headers={"Authorization": "Bearer admin-token"},
        )
        with patch.object(
            views,
            "async_load_speaker_visibility",
            AsyncMock(return_value={"hidden": ["media_player.x"]}),
        ):
            resp = await view.get(req)
        assert resp.status == 200
        assert json.loads(resp.body) == {"shown": [], "hidden": ["media_player.x"]}

    async def test_invalid_payload_is_rejected(self):
        view = views.SpeakerVisibilityView(_hass())
        with patch.object(views, "async_save_speaker_visibility", AsyncMock()) as save:
            resp = await view.post(_post_request(b"[1, 2]", "admin-token"))
        assert resp.status == 400
        save.assert_not_awaited()
