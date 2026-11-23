"""#3580 - two Music Assistant players for one device show as one entry."""

from __future__ import annotations

from custom_components.beatify.services.speaker_shortlist import (
    apply_shortlist,
    find_duplicates,
)


def _p(entity_id, name, state="idle", platform="music_assistant"):
    return {
        "entity_id": entity_id,
        "friendly_name": name,
        "platform": platform,
        "state": state,
    }


# The live case: one bedroom TV, three Music Assistant players, each with its
# own device id and no area.
TV = _p("media_player.tv_schlafzimmer", "TV Schlafzimmer")
TV_PLUS = _p("media_player.tv_schlafzimmer_4", "TV Schlafzimmer+")
TV_DASH = _p("media_player.tv_schlafzimmer_5", "TV Schlafzimmer")
META = {
    "media_player.tv_schlafzimmer": {"device_id": "d1", "area_id": None},
    "media_player.tv_schlafzimmer_4": {"device_id": "d2", "area_id": None},
    "media_player.tv_schlafzimmer_5": {"device_id": "d3", "area_id": None},
}


def test_two_ma_players_for_one_device_show_one_entry():
    dups = find_duplicates([TV_DASH, TV, TV_PLUS], META)
    assert dups == {
        "media_player.tv_schlafzimmer_4": "media_player.tv_schlafzimmer",
        "media_player.tv_schlafzimmer_5": "media_player.tv_schlafzimmer",
    }
    out = apply_shortlist([TV_DASH, TV, TV_PLUS], dups, None)
    shown = [p["entity_id"] for p in out if p["shortlisted"]]
    assert shown == ["media_player.tv_schlafzimmer"]


def test_two_different_devices_both_stay_visible():
    kitchen = _p("media_player.kitchen_ma", "Kitchen")
    living = _p("media_player.living_ma", "Living Room")
    assert find_duplicates([kitchen, living], {}) == {}


def test_same_name_in_different_areas_stays_visible():
    a = _p("media_player.a", "Speaker Left")
    b = _p("media_player.b", "Speaker Left")
    meta = {"media_player.a": {"area_id": "up"}, "media_player.b": {"area_id": "down"}}
    assert find_duplicates([a, b], meta) == {}


def test_available_player_is_kept_over_unavailable_twin():
    gone = _p("media_player.a_tv", "TV", state="unavailable")
    live = _p("media_player.z_tv", "TV")
    assert find_duplicates([gone, live], {}) == {
        "media_player.a_tv": "media_player.z_tv"
    }


def test_unavailable_twin_does_not_hide_available_one():
    gone = _p("media_player.a_tv", "TV", state="unavailable")
    live = _p("media_player.z_tv", "TV")
    dups = find_duplicates([live, gone], {})
    assert "media_player.z_tv" not in dups


def test_native_twin_points_at_the_kept_ma_player():
    sonos = _p("media_player.tv_native", "TV Schlafzimmer Sonos", platform="sonos")
    meta = dict(META)
    meta["media_player.tv_native"] = {"device_id": "d3", "area_id": None}
    dups = find_duplicates([TV, TV_DASH, sonos], meta)
    assert dups["media_player.tv_native"] == "media_player.tv_schlafzimmer"
