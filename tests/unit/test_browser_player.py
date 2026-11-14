"""Play without a speaker: the TV screen or the host's phone plays previews.

Covers the four pieces the feature is made of:

* the preview lookup (``services/playback/previews.py``) — Deezer first, the
  Apple preview when Deezer has none, nothing when neither has one;
* the page registry (``services/playback/browser.py``) — one page per role, a
  "Sound on" claim takes it over, a report only counts from the page that
  plays;
* the media player and announcer the game gets for a browser target
  (``services/browser_player.py``), against the ``MediaPlayerProtocol``;
* the game and server wiring — the 30-second round cap, the state key the TV
  reads, the registration frames on the WebSocket, the status list.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import (
    BROWSER_PREVIEW_SECONDS,
    BROWSER_TARGET_PHONE,
    BROWSER_TARGET_TV,
    DOMAIN,
    ERR_UNAUTHORIZED,
)
from custom_components.beatify.game.protocols import MediaPlayerProtocol
from custom_components.beatify.providers import PLATFORM_BROWSER, get_provider
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from custom_components.beatify.services.browser_player import (
    BrowserPlayerService,
    BrowserTtsService,
    browser_target_players,
    is_browser_target,
)
from custom_components.beatify.services.factories import ha_service_factories
from custom_components.beatify.services.media_player import (
    get_platform_capabilities,
    resolve_entity_platform,
)
from custom_components.beatify.services.playback import (
    BrowserClientRegistry,
    BrowserStrategy,
    build_strategy,
)
from custom_components.beatify.services.playback import browser as browser_mod
from custom_components.beatify.services.playback.previews import (
    Preview,
    apple_track_id,
    async_resolve_preview,
    deezer_track_id,
    parse_deezer_track,
    parse_itunes_lookup,
)
from tests.conftest import make_game_state, make_songs

DEEZER_OK = {
    "id": 3135556,
    "title": "Harder, Better, Faster, Stronger",
    "preview": "https://cdnt-preview.dzcdn.net/api/1/1/a/b/c/0/abc.mp3?hdnea=exp=1",
    "album": {
        "cover_big": "https://e-cdns-images.dzcdn.net/images/cover/x/500x500.jpg",
        "cover_xl": "https://e-cdns-images.dzcdn.net/images/cover/x/1000x1000.jpg",
    },
}
ITUNES_OK = {
    "resultCount": 1,
    "results": [
        {
            "previewUrl": "https://audio-ssl.itunes.apple.com/itunes-assets/x.m4a",
            "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/x/100x100bb.jpg",
        }
    ],
}


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    return ws


# ---------------------------------------------------------------------------
# Preview lookup
# ---------------------------------------------------------------------------


class TestPreviewParsing:
    def test_deezer_answer_gives_the_clip_and_the_cover(self):
        preview = parse_deezer_track(DEEZER_OK)
        assert preview == Preview(
            url=DEEZER_OK["preview"],
            source="deezer",
            album_art=DEEZER_OK["album"]["cover_xl"],
        )

    @pytest.mark.parametrize(
        "data",
        [
            {"error": {"type": "DataException", "code": 800}},
            {**DEEZER_OK, "preview": ""},
            {**DEEZER_OK, "preview": "http://insecure.example/clip.mp3"},
            None,
            [],
        ],
    )
    def test_deezer_without_a_usable_clip_is_no_preview(self, data):
        assert parse_deezer_track(data) is None

    def test_itunes_answer_gives_the_clip_and_a_large_cover(self):
        preview = parse_itunes_lookup(ITUNES_OK)
        assert preview is not None
        assert preview.source == "apple"
        assert preview.url == ITUNES_OK["results"][0]["previewUrl"]
        assert preview.album_art.endswith("600x600bb.jpg")

    def test_itunes_without_results_is_no_preview(self):
        assert parse_itunes_lookup({"resultCount": 0, "results": []}) is None

    def test_track_ids_come_from_the_catalogue_uris(self):
        assert deezer_track_id({"uri_deezer": "deezer://track/3135556"}) == "3135556"
        assert deezer_track_id({"uri_deezer": "https://deezer.com/x"}) is None
        assert deezer_track_id({}) is None
        assert apple_track_id("applemusic://track/697195787") == "697195787"
        assert apple_track_id(None) is None


class _Resp:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def json(self, content_type: Any = None) -> Any:
        return self._payload

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _Session:
    """Answers by URL substring; records every URL it was asked for."""

    def __init__(self, answers: dict[str, tuple[int, Any]]) -> None:
        self.answers = answers
        self.urls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> _Resp:
        self.urls.append(url)
        for key, (status, payload) in self.answers.items():
            if key in url:
                return _Resp(status, payload)
        return _Resp(404, None)


class TestPreviewResolution:
    async def test_deezer_wins_when_it_has_a_clip(self):
        session = _Session({"api.deezer.com": (200, DEEZER_OK)})
        song = {"uri_deezer": "deezer://track/3135556"}
        preview = await async_resolve_preview(
            session, song, apple_uri="applemusic://track/1"
        )
        assert preview is not None and preview.source == "deezer"
        assert session.urls == ["https://api.deezer.com/track/3135556"]

    async def test_apple_steps_in_when_deezer_has_no_clip(self):
        session = _Session(
            {
                "api.deezer.com": (200, {**DEEZER_OK, "preview": ""}),
                "itunes.apple.com": (200, ITUNES_OK),
            }
        )
        song = {"uri_deezer": "deezer://track/3135556"}
        preview = await async_resolve_preview(
            session, song, apple_uri="applemusic://track/697195787", storefront="de"
        )
        assert preview is not None and preview.source == "apple"
        assert "id=697195787" in session.urls[1]
        assert "country=de" in session.urls[1]

    async def test_apple_alone_when_the_song_has_no_deezer_id(self):
        session = _Session({"itunes.apple.com": (200, ITUNES_OK)})
        preview = await async_resolve_preview(
            session, {}, apple_uri="applemusic://track/697195787"
        )
        assert preview is not None and preview.source == "apple"
        assert len(session.urls) == 1

    async def test_nothing_anywhere_is_none(self):
        session = _Session({"api.deezer.com": (500, None)})
        song = {"uri_deezer": "deezer://track/1"}
        assert await async_resolve_preview(session, song, apple_uri=None) is None


# ---------------------------------------------------------------------------
# Page registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_first_page_takes_a_free_role(self):
        reg = BrowserClientRegistry()
        tv = _ws()
        assert reg.register("tv", tv) is None
        assert reg.holds("tv", tv)
        assert reg.status() == {"tv": True, "phone": False}

    def test_a_second_page_does_not_displace_without_a_claim(self):
        reg = BrowserClientRegistry()
        first, second = _ws(), _ws()
        reg.register("tv", first)
        assert reg.register("tv", second) is None
        assert reg.holds("tv", first)

    def test_a_claim_takes_the_role_and_names_the_loser(self):
        reg = BrowserClientRegistry()
        first, second = _ws(), _ws()
        reg.register("tv", first)
        assert reg.register("tv", second, claim=True) is first
        assert reg.holds("tv", second)

    def test_a_closed_holder_is_replaced_by_a_plain_registration(self):
        reg = BrowserClientRegistry()
        first, second = _ws(), _ws()
        reg.register("tv", first)
        first.closed = True
        reg.register("tv", second)
        assert reg.holds("tv", second)

    def test_unregister_frees_the_role(self):
        reg = BrowserClientRegistry()
        tv = _ws()
        reg.register("tv", tv)
        assert reg.unregister(tv) == ["tv"]
        assert reg.connected("tv") is False
        assert reg.playback_state("tv") is None

    def test_unknown_role_is_refused(self):
        with pytest.raises(ValueError):
            BrowserClientRegistry().register("fridge", _ws())

    async def test_request_returns_the_report_for_its_id(self):
        reg = BrowserClientRegistry()
        tv = _ws()
        reg.register("tv", tv)

        async def answer(message: dict) -> None:
            reg.handle_report(tv, {"state": "playing", "id": message["id"]})

        tv.send_json.side_effect = answer
        reply = await reg.request("tv", {"type": "x"}, timeout=1)
        assert reply == {"state": "playing"}
        assert reg.playback_state("tv") == "playing"

    async def test_request_without_a_page_is_unsent(self):
        reply = await BrowserClientRegistry().request("tv", {}, timeout=1)
        assert reply == {"state": "unsent"}

    async def test_request_times_out_quietly(self):
        reg = BrowserClientRegistry()
        reg.register("tv", _ws())
        assert await reg.request("tv", {}, timeout=0.01) == {"state": "timeout"}

    def test_a_report_from_a_page_without_a_role_is_ignored(self):
        reg = BrowserClientRegistry()
        reg.register("tv", _ws())
        assert reg.handle_report(_ws(), {"state": "ended"}) is False
        assert reg.playback_state("tv") == "idle"

    def test_an_unknown_report_state_is_ignored(self):
        reg = BrowserClientRegistry()
        tv = _ws()
        reg.register("tv", tv)
        assert reg.handle_report(tv, {"state": "exploded"}) is False


# ---------------------------------------------------------------------------
# Strategy and service
# ---------------------------------------------------------------------------

SONG = {
    "title": "One More Time",
    "artist": "Daft Punk",
    "year": 2000,
    "uri_deezer": "deezer://track/3135553",
    "_resolved_uri": "deezer://track/3135553",
}
PREVIEW = Preview(
    url="https://cdnt-preview.dzcdn.net/clip.mp3",
    source="deezer",
    album_art="https://e-cdns-images.dzcdn.net/cover.jpg",
)


def _service(
    entity_id: str = BROWSER_TARGET_TV,
) -> tuple[BrowserPlayerService, BrowserClientRegistry]:
    reg = BrowserClientRegistry()
    service = BrowserPlayerService(MagicMock(), entity_id, clients=reg)
    return service, reg


def _answering(reg: BrowserClientRegistry, ws: AsyncMock, state: str) -> None:
    async def answer(message: dict) -> None:
        if "id" in message:
            reg.handle_report(ws, {"state": state, "id": message["id"]})

    ws.send_json.side_effect = answer


class TestBrowserPlayerService:
    def test_it_is_a_media_player_to_the_game(self):
        service, _ = _service()
        assert isinstance(service, MediaPlayerProtocol)

    async def test_no_page_is_a_systemic_error(self):
        service, _ = _service()
        # The round start pauses on verify_responsive, whose reason says what
        # to do; is_available stays True so it is the one that answers.
        assert service.is_available() is True
        ok, detail = await service.verify_responsive()
        assert ok is False and "TV" in detail
        assert await service.play_song(SONG) is False
        assert service.last_failure_reason == "error"

    async def test_a_song_without_a_preview_is_skipped_quietly(self):
        service, reg = _service()
        reg.register("tv", _ws())
        with patch.object(BrowserStrategy, "_resolve", AsyncMock(return_value=None)):
            assert await service.play_song(SONG) is False
        assert service.last_failure_reason == "unavailable"

    async def test_the_clip_goes_to_the_page_and_its_cover_to_the_reveal(self):
        service, reg = _service()
        tv = _ws()
        reg.register("tv", tv)
        _answering(reg, tv, "playing")
        with patch.object(BrowserStrategy, "_resolve", AsyncMock(return_value=PREVIEW)):
            assert await service.play_song(SONG) is True
        sent = tv.send_json.call_args_list[0][0][0]
        assert sent["type"] == "browser_audio"
        assert sent["action"] == "play"
        assert sent["url"] == PREVIEW.url
        # Only the clip travels to the page: no track id, title or year.
        assert set(sent) == {"type", "action", "url", "id"}
        assert service.last_failure_reason is None
        assert service.last_attempted_uri == SONG["_resolved_uri"]
        meta = await service.wait_for_metadata_update(SONG["_resolved_uri"])
        assert meta["album_art"].startswith("/beatify/api/albumart?url=")

    async def test_a_clip_the_browser_cannot_load_skips_the_song(self):
        service, reg = _service()
        tv = _ws()
        reg.register("tv", tv)
        _answering(reg, tv, "error")
        with patch.object(BrowserStrategy, "_resolve", AsyncMock(return_value=PREVIEW)):
            assert await service.play_song(SONG) is False
        assert service.last_failure_reason == "unavailable"

    async def test_a_tv_waiting_for_sound_on_counts_as_started(self):
        service, reg = _service()
        tv = _ws()
        reg.register("tv", tv)
        _answering(reg, tv, "blocked")
        with patch.object(BrowserStrategy, "_resolve", AsyncMock(return_value=PREVIEW)):
            assert await service.play_song(SONG) is True
        assert service.get_playback_state() == "playing"

    async def test_a_slow_page_is_trusted(self, monkeypatch):
        monkeypatch.setattr(browser_mod, "PLAY_ACK_TIMEOUT", 0.01)
        service, reg = _service()
        reg.register("tv", _ws())
        with patch.object(BrowserStrategy, "_resolve", AsyncMock(return_value=PREVIEW)):
            assert await service.play_song(SONG) is True

    async def test_stop_resume_and_volume_reach_the_page(self):
        service, reg = _service(BROWSER_TARGET_PHONE)
        phone = _ws()
        reg.register("phone", phone)
        assert await service.stop() is True
        assert await service.play() is True
        assert await service.set_volume(1.7) is True
        actions = [c[0][0]["action"] for c in phone.send_json.call_args_list]
        assert actions == ["stop", "resume", "volume"]
        assert phone.send_json.call_args_list[-1][0][0]["level"] == 1.0
        assert service.get_volume() == 1.0

    def test_song_end_reads_as_idle_for_the_auto_advance(self):
        service, reg = _service()
        tv = _ws()
        reg.register("tv", tv)
        assert service.get_playback_state() == "playing"
        reg.handle_report(tv, {"state": "ended"})
        assert service.get_playback_state() == "idle"
        reg.unregister(tv)
        assert service.get_playback_state() is None

    async def test_nothing_to_save_or_restore(self):
        service, _ = _service()
        service.save_volume()
        assert await service.restore_volume() is True
        assert await service.restore_queue() is True
        assert service.snapshot_saved_states() == {}


class TestBrowserTts:
    async def test_the_announcement_url_goes_to_the_same_page(self):
        reg = BrowserClientRegistry()
        tv = _ws()
        reg.register("tv", tv)
        tts = BrowserTtsService(
            MagicMock(),
            tts_entity_id="tts.cloud",
            target_entity_id=BROWSER_TARGET_TV,
            clients=reg,
        )
        with patch.object(
            BrowserTtsService,
            "_audio_url",
            AsyncMock(return_value="/api/tts_proxy/abc.mp3"),
        ):
            await tts.speak("Round one", "de")
        tv.send_json.assert_awaited_once_with(
            {
                "type": "browser_audio",
                "action": "announce",
                "url": "/api/tts_proxy/abc.mp3",
            }
        )

    async def test_no_page_no_announcement(self):
        tts = BrowserTtsService(
            MagicMock(),
            tts_entity_id="tts.cloud",
            target_entity_id=BROWSER_TARGET_TV,
            clients=BrowserClientRegistry(),
        )
        with patch.object(BrowserTtsService, "_audio_url", AsyncMock()) as url:
            await tts.speak("Round one")
        url.assert_not_awaited()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


class TestWiring:
    def test_targets_are_recognised(self):
        assert is_browser_target(BROWSER_TARGET_TV)
        assert is_browser_target(BROWSER_TARGET_PHONE)
        assert not is_browser_target("media_player.kitchen")
        assert not is_browser_target(None)

    def test_the_platform_is_fixed_by_the_id(self):
        assert resolve_entity_platform(MagicMock(), BROWSER_TARGET_TV) == (
            PLATFORM_BROWSER
        )

    def test_a_browser_plays_deezer_and_nothing_else(self):
        caps = get_platform_capabilities(PLATFORM_BROWSER)
        assert caps["supported"] is True
        assert caps["deezer"] is True
        assert caps["spotify"] is False
        assert get_provider("deezer").plays_on(PLATFORM_BROWSER)

    def test_the_strategy_is_reached_through_the_dispatch(self):
        from custom_components.beatify.services.playback import PlayerContext

        ctx = PlayerContext(MagicMock(), BROWSER_TARGET_TV, platform=PLATFORM_BROWSER)
        assert isinstance(build_strategy(ctx), BrowserStrategy)

    def test_the_factories_build_browser_services(self):
        reg = BrowserClientRegistry()
        factories = ha_service_factories(MagicMock(), browser_clients=reg)
        player = factories.media_player(BROWSER_TARGET_TV, provider="deezer")
        assert isinstance(player, BrowserPlayerService)
        tts = factories.tts(
            tts_entity_id="tts.cloud", media_player_entity_id=BROWSER_TARGET_PHONE
        )
        assert isinstance(tts, BrowserTtsService)

    def test_status_list_entries_look_like_speakers(self):
        reg = BrowserClientRegistry()
        players = browser_target_players(reg)
        assert [p["entity_id"] for p in players] == [
            BROWSER_TARGET_TV,
            BROWSER_TARGET_PHONE,
        ]
        tv, phone = players
        assert tv["connected"] is False
        assert phone["connected"] is True
        assert tv["supports_deezer"] is True
        assert tv["supports_spotify"] is False
        assert tv["platform"] == PLATFORM_BROWSER
        reg.register("tv", _ws())
        assert browser_target_players(reg)[0]["connected"] is True


class TestRoundCap:
    def test_a_browser_target_caps_the_round_at_the_preview(self):
        gs = make_game_state()
        gs.round_duration = 45
        gs.platform = PLATFORM_BROWSER
        assert gs.round_duration == BROWSER_PREVIEW_SECONDS
        gs.platform = "sonos"
        assert gs.round_duration == 45

    def test_a_shorter_round_stays_as_chosen(self):
        gs = make_game_state()
        gs.platform = PLATFORM_BROWSER
        gs.round_duration = 15
        assert gs.round_duration == 15

    def test_create_game_on_the_tv(self):
        from custom_components.beatify.game.config import GameOptions

        gs = make_game_state()
        songs = make_songs(5)
        for i, song in enumerate(songs):
            song["uri_deezer"] = f"deezer://track/{1000 + i}"
        gs.create_game(
            playlists=["test.json"],
            songs=songs,
            media_player=BROWSER_TARGET_TV,
            base_url="http://localhost:8123",
            options=GameOptions(
                provider="deezer", platform=PLATFORM_BROWSER, round_duration=60
            ),
        )
        assert gs.round_duration == BROWSER_PREVIEW_SECONDS
        assert gs.browser_playback == "tv"
        assert gs.get_state()["browser_playback"] == "tv"


class TestWebSocketRegistration:
    def _handler(self, *, with_game: bool = False) -> BeatifyWebSocketHandler:
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        if with_game:
            gs = make_game_state()
            gs.create_game(
                playlists=["test.json"],
                songs=make_songs(3),
                media_player="media_player.test",
                base_url="http://localhost:8123",
            )
            hass.data[DOMAIN]["game"] = gs
        return BeatifyWebSocketHandler(hass, browser_clients=BrowserClientRegistry())

    async def test_the_tv_registers_before_any_game_exists(self):
        handler = self._handler()
        tv = _ws()
        await handler._handle_message(tv, {"type": "playback_register", "role": "tv"})
        tv.send_json.assert_awaited_with(
            {"type": "playback_registered", "role": "tv", "active": True}
        )
        assert handler.browser_clients.holds("tv", tv)

    async def test_a_second_tv_stands_by_until_it_claims(self):
        handler = self._handler()
        first, second = _ws(), _ws()
        await handler._handle_message(
            first, {"type": "playback_register", "role": "tv"}
        )
        await handler._handle_message(
            second, {"type": "playback_register", "role": "tv"}
        )
        assert second.send_json.call_args[0][0]["active"] is False
        await handler._handle_message(
            second, {"type": "playback_register", "role": "tv", "claim": True}
        )
        first.send_json.assert_awaited_with({"type": "playback_released", "role": "tv"})
        assert handler.browser_clients.holds("tv", second)

    async def test_the_phone_role_needs_the_host_login(self):
        handler = self._handler()
        stranger = _ws()
        with patch(
            "custom_components.beatify.server.websocket._is_ha_authenticated",
            return_value=False,
        ):
            await handler._handle_message(
                stranger, {"type": "playback_register", "role": "phone"}
            )
        assert stranger.send_json.call_args[0][0]["code"] == ERR_UNAUTHORIZED
        assert not handler.browser_clients.connected("phone")

    async def test_an_admin_socket_may_play_as_the_phone(self):
        handler = self._handler()
        admin = _ws()
        handler.add_admin_socket(admin)
        await handler._handle_message(
            admin, {"type": "playback_register", "role": "phone"}
        )
        assert handler.browser_clients.holds("phone", admin)

    async def test_reports_are_taken_without_a_game(self):
        handler = self._handler()
        tv = _ws()
        await handler._handle_message(tv, {"type": "playback_register", "role": "tv"})
        await handler._handle_message(tv, {"type": "playback_report", "state": "ended"})
        assert handler.browser_clients.playback_state("tv") == "ended"

    async def test_disconnect_frees_the_role(self):
        handler = self._handler(with_game=True)
        tv = _ws()
        await handler._handle_message(tv, {"type": "playback_register", "role": "tv"})
        await handler._handle_disconnect(tv)
        assert not handler.browser_clients.connected("tv")


def test_websocket_handler_requires_browser_clients() -> None:
    """#3473: no silent private registry; the registry is a required argument."""
    with pytest.raises(TypeError):
        BeatifyWebSocketHandler(MagicMock())  # type: ignore[call-arg]
