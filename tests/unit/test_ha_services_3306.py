"""#3306 — Home Assistant actions and events for a running game.

The issue: Beatify exposed its state to HA as sensors (#441) but HA could not
act on it, so the obvious party automation — doorbell rings, the game pauses
with "Someone at the door" on every screen — was impossible.

What is worth failing a build over:

1. **Each action does what the host's button does.** pause (with the door
   reason), resume, next round, end game — against a real ``GameState`` and
   the real websocket handler, not a mock of either.
2. **Who may call them.** A Home Assistant user who is not an admin is
   refused with ``Unauthorized`` and the game does not move. A call without a
   user — an automation — is allowed, because that is the doorbell.
3. **A refusal is a clean, translated error.** No game, or a phase that does
   not allow the action, raises ``ServiceValidationError`` with a translation
   key that exists in every language file.
4. **The events fire once, at the right moment, with public data only.**
   ``beatify_round_revealed`` after the reveal is broadcast and never during
   PLAYING; ``beatify_game_ended`` once, with the podium.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import (
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)

from custom_components.beatify.const import (
    ADMIN_DISCONNECT_PAUSE_REASON,
    DOMAIN,
    EVENT_GAME_ENDED,
    EVENT_ROUND_REVEALED,
    HOST_PAUSE_REASON,
    HOST_PAUSE_REASON_DOOR,
    SERVICE_PAUSE_REASONS,
    SERVICES,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.ha_services import (
    async_register_services,
    async_unregister_services,
)
from custom_components.beatify.server.serializers import (
    build_state_message,
    redact_state_for_player,
)
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from custom_components.beatify.server.ws_handlers._helpers import finalize_and_end
from tests.conftest import make_game_state, make_songs

ADMIN_ID = "user-admin"
GUEST_ID = "user-guest"

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"


# ---------------------------------------------------------------------------
# A Home Assistant that records what the integration does with it
# ---------------------------------------------------------------------------


class _FakeServices:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str], object] = {}

    def async_register(self, domain, service, handler, schema=None) -> None:
        self.handlers[(domain, service)] = handler

    def async_remove(self, domain, service) -> None:
        self.handlers.pop((domain, service), None)


class _FakeBus:
    def __init__(self, timeline: list) -> None:
        self.events: list[tuple[str, dict]] = []
        self._timeline = timeline

    def async_fire(self, event_type, event_data=None) -> None:
        self.events.append((event_type, event_data))
        self._timeline.append(("event", event_type))


class _FakeAuth:
    """Models HA's user store: an admin, a non-admin, and nobody else."""

    def __init__(self) -> None:
        self._users = {
            ADMIN_ID: SimpleNamespace(id=ADMIN_ID, is_admin=True),
            GUEST_ID: SimpleNamespace(id=GUEST_ID, is_admin=False),
        }

    async def async_get_user(self, user_id):
        return self._users.get(user_id)


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    svc.play = AsyncMock(return_value=True)
    svc.wait_for_metadata_update = AsyncMock(return_value={})
    svc.get_playback_state.return_value = "playing"
    return svc


async def _setup(*, rounds: int = 4, start: bool = True):
    """Real GameState + real websocket handler, wired like __init__.py."""
    timeline: list = []
    hass = MagicMock()
    hass.services = _FakeServices()
    hass.bus = _FakeBus(timeline)
    hass.auth = _FakeAuth()

    game_state = make_game_state()
    handler = BeatifyWebSocketHandler(hass)
    hass.data = {DOMAIN: {"game": game_state, "ws_handler": handler}}

    real_broadcast_state = handler.broadcast_state

    async def _recording_broadcast_state():
        timeline.append(("broadcast", game_state.phase))
        await real_broadcast_state()

    handler.broadcast_state = _recording_broadcast_state  # type: ignore[method-assign]
    game_state.set_round_end_callback(handler.broadcast_round_end)

    async def _game_end():
        await finalize_and_end(handler, game_state)

    game_state.set_game_end_callback(_game_end)

    game_state.create_game(
        playlists=["t.json"],
        songs=make_songs(rounds),
        media_player="media_player.x",
        base_url="http://h",
    )
    game_state._media_player_service = _stub_media_service()
    game_state.platform = "music_assistant"
    for name in ("Alice", "Bob"):
        ws = MagicMock()
        ws.closed = False
        game_state.add_player(name, ws)
        game_state.get_player(name).connected = True
    if start:
        assert await game_state.start_round()
        assert game_state.phase == GamePhase.PLAYING

    async_register_services(hass)
    return hass, game_state, handler, timeline


async def _call(hass, service: str, data: dict | None = None, user_id=None):
    call = SimpleNamespace(
        domain=DOMAIN,
        service=service,
        data=data or {},
        context=SimpleNamespace(user_id=user_id),
    )
    game_state = hass.data.get(DOMAIN, {}).get("game")
    if game_state is not None and game_state.round_start_time is not None:
        # #3340: a next_round in the first seconds of a round is treated as
        # stale. These tests drive rounds back to back, so age the round first.
        game_state.round_start_time -= 10
    await hass.services.handlers[(DOMAIN, service)](call)


# ---------------------------------------------------------------------------
# 0. Registration
# ---------------------------------------------------------------------------


async def test_the_four_actions_are_registered_and_removed_again():
    hass, *_ = await _setup(start=False)

    assert set(hass.services.handlers) == {(DOMAIN, s) for s in SERVICES}
    assert set(SERVICES) == {"pause_game", "resume_game", "next_round", "end_game"}

    async_unregister_services(hass)
    assert hass.services.handlers == {}


async def test_setup_entry_registers_the_actions():
    """The composition root wires them in, and unload takes them out."""
    import custom_components.beatify as beatify_init

    source = Path(beatify_init.__file__).read_text(encoding="utf-8")
    assert "async_register_services(hass)" in source
    assert "async_unregister_services(hass)" in source


# ---------------------------------------------------------------------------
# 1. Each action does what the host's button does
# ---------------------------------------------------------------------------


class TestActions:
    async def test_doorbell_pause_shows_the_door_reason_everywhere(self):
        hass, game_state, _, _ = await _setup()

        await _call(hass, "pause_game", {"reason": "door"})

        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == HOST_PAUSE_REASON_DOOR
        # The same chip on every surface: the admin/TV frame and the redacted
        # frame every player phone receives both carry the reason.
        state = build_state_message(game_state)
        assert state["pause_reason"] == HOST_PAUSE_REASON_DOOR
        assert redact_state_for_player(state)["pause_reason"] == (
            HOST_PAUSE_REASON_DOOR
        )
        game_state._media_player_service.stop.assert_awaited()

    async def test_each_short_reason_maps_to_a_host_pause_reason(self):
        for short, reason in SERVICE_PAUSE_REASONS.items():
            hass, game_state, _, _ = await _setup()
            await _call(hass, "pause_game", {"reason": short})
            assert game_state.pause_reason == reason

    async def test_pause_without_reason_is_a_plain_pause(self):
        hass, game_state, _, _ = await _setup()

        await _call(hass, "pause_game")

        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == HOST_PAUSE_REASON

    async def test_resume_lifts_the_pause(self):
        hass, game_state, _, _ = await _setup()
        await _call(hass, "pause_game", {"reason": "food"})

        await _call(hass, "resume_game")

        assert game_state.phase == GamePhase.PLAYING
        assert game_state.pause_reason is None

    async def test_next_round_reveals_then_starts_the_next_round(self):
        hass, game_state, _, _ = await _setup()

        await _call(hass, "next_round")
        assert game_state.phase == GamePhase.REVEAL
        assert game_state.round == 1

        await _call(hass, "next_round")
        assert game_state.phase == GamePhase.PLAYING
        assert game_state.round == 2

    async def test_end_game_goes_to_the_podium(self):
        hass, game_state, _, _ = await _setup()

        await _call(hass, "end_game")

        assert game_state.phase == GamePhase.END


# ---------------------------------------------------------------------------
# 2. Who may call them
# ---------------------------------------------------------------------------


class TestAuthorization:
    @pytest.mark.parametrize("service", SERVICES)
    async def test_a_non_admin_user_is_refused_and_nothing_moves(self, service):
        hass, game_state, _, timeline = await _setup()
        before = (game_state.phase, game_state.round, game_state.pause_reason)

        with pytest.raises(Unauthorized):
            await _call(hass, service, user_id=GUEST_ID)

        assert (game_state.phase, game_state.round, game_state.pause_reason) == (before)
        assert hass.bus.events == []

    async def test_an_unknown_user_is_refused(self):
        hass, game_state, _, _ = await _setup()

        with pytest.raises(UnknownUser):
            await _call(hass, "pause_game", {"reason": "door"}, user_id="ghost")

        assert game_state.phase == GamePhase.PLAYING

    async def test_an_admin_user_is_allowed(self):
        hass, game_state, _, _ = await _setup()

        await _call(hass, "pause_game", {"reason": "door"}, user_id=ADMIN_ID)

        assert game_state.phase == GamePhase.PAUSED

    async def test_an_automation_without_a_user_is_allowed(self):
        """The doorbell: HA calls the action itself, context.user_id is None."""
        hass, game_state, _, _ = await _setup()

        await _call(hass, "pause_game", {"reason": "door"}, user_id=None)

        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == HOST_PAUSE_REASON_DOOR


# ---------------------------------------------------------------------------
# 3. Clean, translated refusals
# ---------------------------------------------------------------------------


def _exception_keys(lang: str) -> set[str]:
    data = json.loads((COMPONENT / "translations" / f"{lang}.json").read_text())
    return set(data.get("exceptions", {}))


class TestRefusals:
    @pytest.mark.parametrize("service", SERVICES)
    async def test_no_game_running(self, service):
        hass, game_state, _, _ = await _setup(start=False)
        game_state.game_id = None

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, service)

        assert err.value.translation_domain == DOMAIN
        assert err.value.translation_key == "no_active_game"

    async def test_integration_not_set_up(self):
        hass, _, _, _ = await _setup(start=False)
        hass.data = {}

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "end_game")

        assert err.value.translation_key == "no_active_game"

    @pytest.mark.parametrize(
        ("service", "key"),
        [
            ("pause_game", "no_round_to_pause"),
            ("resume_game", "not_paused"),
            ("next_round", "cannot_advance"),
            ("end_game", "cannot_end_now"),
        ],
    )
    async def test_phase_does_not_allow_it(self, service, key):
        """The lobby: a game exists, but no round is running."""
        hass, game_state, _, _ = await _setup(start=False)
        assert game_state.phase == GamePhase.LOBBY

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, service)

        assert err.value.translation_key == key
        assert game_state.phase == GamePhase.LOBBY

    async def test_resume_while_playing_is_refused(self):
        hass, game_state, _, _ = await _setup()

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "resume_game")

        assert err.value.translation_key == "not_paused"
        assert game_state.phase == GamePhase.PLAYING

    async def test_a_server_owned_pause_cannot_be_relabelled_by_the_doorbell(self):
        hass, game_state, _, _ = await _setup()
        await game_state.pause_game(ADMIN_DISCONNECT_PAUSE_REASON)

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "pause_game", {"reason": "door"})

        assert err.value.translation_key == "pause_not_host"
        assert game_state.pause_reason == ADMIN_DISCONNECT_PAUSE_REASON

    async def test_an_unknown_reason_is_refused(self):
        hass, game_state, _, _ = await _setup()

        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "pause_game", {"reason": "pizza"})

        assert err.value.translation_key == "unknown_pause_reason"
        assert game_state.phase == GamePhase.PLAYING

    @pytest.mark.parametrize("lang", ["en", "de", "es", "fr", "it", "nl"])
    def test_every_refusal_key_is_translated(self, lang):
        from custom_components.beatify import ha_services

        needed = set(ha_services._REFUSAL_TRANSLATION_KEYS.values()) | {
            "no_active_game",
            "action_refused",
        }
        assert needed <= _exception_keys(lang)


# ---------------------------------------------------------------------------
# 4. Events
# ---------------------------------------------------------------------------


def _events(hass, event_type: str) -> list[dict]:
    return [data for etype, data in hass.bus.events if etype == event_type]


class TestRoundRevealedEvent:
    async def test_not_fired_while_the_round_is_playing(self):
        hass, game_state, handler, _ = await _setup()

        await handler.broadcast_round_end()

        assert game_state.phase == GamePhase.PLAYING
        assert _events(hass, EVENT_ROUND_REVEALED) == []

    async def test_fired_once_after_the_reveal_is_broadcast(self):
        hass, game_state, handler, timeline = await _setup()

        await _call(hass, "next_round")

        events = _events(hass, EVENT_ROUND_REVEALED)
        assert len(events) == 1
        # The room first, the bus second.
        reveal_broadcast = timeline.index(("broadcast", GamePhase.REVEAL))
        fired = timeline.index(("event", EVENT_ROUND_REVEALED))
        assert reveal_broadcast < fired

        # A second broadcast of the same reveal does not fire it again.
        await handler.broadcast_round_end()
        assert len(_events(hass, EVENT_ROUND_REVEALED)) == 1

    async def test_payload_is_the_public_reveal_and_nothing_more(self):
        hass, game_state, _, _ = await _setup()
        song = dict(game_state.current_song)

        await _call(hass, "next_round")

        (payload,) = _events(hass, EVENT_ROUND_REVEALED)
        assert payload["game_id"] == game_state.game_id
        assert payload["round"] == 1
        assert payload["total_rounds"] == game_state.total_rounds
        assert payload["last_round"] is False
        assert payload["voided"] is False
        assert payload["song"] == {
            "artist": song["artist"],
            "title": song["title"],
            "year": song["year"],
        }
        assert set(payload["leaders"]) <= {"Alice", "Bob"}
        # No playable URIs, no admin-only fields, no player sessions.
        flat = json.dumps(payload)
        assert "spotify:" not in flat
        assert "uri" not in flat
        assert "fun_fact" not in flat
        assert "session" not in flat

    async def test_each_round_fires_its_own_event(self):
        hass, _, _, _ = await _setup()

        await _call(hass, "next_round")  # reveal round 1
        await _call(hass, "next_round")  # start round 2
        await _call(hass, "next_round")  # reveal round 2

        rounds = [p["round"] for p in _events(hass, EVENT_ROUND_REVEALED)]
        assert rounds == [1, 2]

    async def test_a_voided_round_is_marked(self):
        hass, game_state, _, _ = await _setup()

        await game_state.void_round(None)

        (payload,) = _events(hass, EVENT_ROUND_REVEALED)
        assert payload["voided"] is True


class TestGameEndedEvent:
    async def test_end_game_fires_once_with_the_podium(self):
        hass, game_state, _, timeline = await _setup()
        game_state.get_player("Alice").score = 30
        game_state.get_player("Bob").score = 10

        await _call(hass, "end_game")

        (payload,) = _events(hass, EVENT_GAME_ENDED)
        assert game_state.phase == GamePhase.END
        assert payload["game_id"] == game_state.game_id
        assert payload["winners"] == ["Alice"]
        assert payload["leaderboard"] == [
            {"rank": 1, "name": "Alice", "score": 30},
            {"rank": 2, "name": "Bob", "score": 10},
        ]
        # Only rank/name/score: the podium, not the per-player stat dump.
        assert all(set(e) == {"rank", "name", "score"} for e in payload["leaderboard"])

        # A second end attempt is refused and does not fire again.
        with pytest.raises(ServiceValidationError):
            await _call(hass, "end_game")
        assert len(_events(hass, EVENT_GAME_ENDED)) == 1

    async def test_the_last_next_round_ends_the_game_and_fires(self):
        hass, game_state, _, _ = await _setup(rounds=2)

        await _call(hass, "next_round")  # reveal round 1
        await _call(hass, "next_round")  # start round 2, the last one
        await _call(hass, "next_round")  # reveal round 2
        assert game_state.last_round
        assert _events(hass, EVENT_GAME_ENDED) == []
        await _call(hass, "next_round")  # past the last reveal → podium

        assert game_state.phase == GamePhase.END
        assert len(_events(hass, EVENT_GAME_ENDED)) == 1

    async def test_a_refused_end_does_not_fire(self):
        hass, _, _, _ = await _setup(start=False)

        with pytest.raises(ServiceValidationError):
            await _call(hass, "end_game")

        assert _events(hass, EVENT_GAME_ENDED) == []


# ---------------------------------------------------------------------------
# 5. services.yaml + translations agree
# ---------------------------------------------------------------------------


def test_services_yaml_and_translations_describe_every_action():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    assert set(services) == set(SERVICES)
    options = services["pause_game"]["fields"]["reason"]["selector"]["select"][
        "options"
    ]
    assert options == list(SERVICE_PAUSE_REASONS)

    for lang in ("en", "de", "es", "fr", "it", "nl"):
        data = json.loads((COMPONENT / "translations" / f"{lang}.json").read_text())
        for service in SERVICES:
            entry = data["services"][service]
            assert entry["name"] and entry["description"], (lang, service)
        assert set(data["services"]["pause_game"]["fields"]) == {"reason"}
        assert set(data["selector"]["pause_reason"]["options"]) == set(
            SERVICE_PAUSE_REASONS
        )
