"""#2649 — the host can take the party lights back mid-game.

The scene from the issue: 10pm, the hallway and the living room flash at every
reveal, a child asleep upstairs. Turning them off meant ending the game — the
lights are configured at start (`game_views.py:579-587`), the setup section is
hidden during play (`admin.js:311`), and the phone had no control at all
(`player.html:981-1001`). Three WebSocket handlers existed for exactly this
(`ws_handlers/admin.py:108-110`) and no client had ever sent one.

The server side of the fix is two small things, and the second is the one that
is easy to get wrong:

1. **The state says what the lights are doing.** Without it the phone cannot
   report anything, and the host's first sign that lights are running stays the
   hallway flashing.

2. **The configuration outlives being switched off.** `disable_party_lights()`
   drops the service, and the entity list lives inside it. If the config went
   with it, "off" would be a one-way door: the host silences the lights at 10pm
   and cannot bring them back for the next game — the same trap the issue
   describes, only pointing the other way.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataclasses import replace

from custom_components.beatify.game.serializers import _party_lights_state
from custom_components.beatify.server.serializers import _PLAYER_VISIBLE_ROUND
from tests.conftest import make_game_state


def _lights_service() -> MagicMock:
    """A party-lights service stub with the async surface the state calls."""
    svc = MagicMock()
    svc.start = AsyncMock()
    svc.stop = AsyncMock()
    svc.snapshot_saved_states = MagicMock(return_value=None)
    return svc


def _state_with_lights_factory():
    gs = make_game_state()
    # GameOutputFactories is frozen — swap the whole record rather than poke it.
    gs._service_factories = replace(gs._service_factories, party_lights=_lights_service)
    return gs


class TestConfigIsRemembered:
    @pytest.mark.asyncio
    async def test_configuring_records_what_was_set(self):
        gs = _state_with_lights_factory()

        await gs.configure_party_lights(
            ["light.wohnzimmer", "light.flur"], "subtle", "dynamic", None
        )

        assert gs.party_lights_config == {
            "entity_ids": ["light.wohnzimmer", "light.flur"],
            "intensity": "subtle",
            "light_mode": "dynamic",
            "wled_presets": None,
        }

    @pytest.mark.asyncio
    async def test_switching_off_keeps_the_configuration(self):
        """The one-way-door regression.

        If this list went away with the service, the host who silenced the
        lights at 10pm would have no way to switch them back on — the phone
        needs the entity ids to re-configure them.
        """
        gs = _state_with_lights_factory()
        await gs.configure_party_lights(["light.wohnzimmer"], "party", "dynamic", None)

        await gs.disable_party_lights()

        assert gs._party_lights is None  # the service really is gone
        assert gs.party_lights_config["entity_ids"] == ["light.wohnzimmer"]

    @pytest.mark.asyncio
    async def test_the_stored_entity_list_is_a_copy(self):
        gs = _state_with_lights_factory()
        entities = ["light.wohnzimmer"]

        await gs.configure_party_lights(entities, "party", "dynamic", None)
        entities.append("light.kueche")

        assert gs.party_lights_config["entity_ids"] == ["light.wohnzimmer"]

    def test_nothing_is_claimed_before_lights_are_set_up(self):
        assert make_game_state().party_lights_config is None


class TestSerialisation:
    @pytest.mark.asyncio
    async def test_active_mirrors_the_live_service(self):
        gs = _state_with_lights_factory()
        await gs.configure_party_lights(["light.flur"], "subtle", "dynamic", None)

        assert _party_lights_state(gs) == {
            "configured": True,
            "active": True,
            "intensity": "subtle",
            "entity_ids": ["light.flur"],
        }

        await gs.disable_party_lights()
        # Still configured — but no longer running. The phone needs both facts
        # to draw "off" and still offer a way back.
        after = _party_lights_state(gs)
        assert after["configured"] is True
        assert after["active"] is False
        assert after["entity_ids"] == ["light.flur"]

    def test_nothing_is_sent_when_no_lights_were_ever_configured(self):
        # A three-way control for a feature the host never set up would be an
        # advert, not a control — the client hides the row on a null block.
        assert _party_lights_state(make_game_state()) is None

    def test_players_receive_the_block(self):
        # Same shape as volume_level: everyone gets the frame, only the host
        # renders it. Filtering it out would leave the host's own phone blind,
        # because the host is a player too.
        assert "party_lights" in _PLAYER_VISIBLE_ROUND
