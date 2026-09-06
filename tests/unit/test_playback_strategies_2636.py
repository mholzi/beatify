"""#2636: one platform at a time.

``MediaPlayerService`` used to hold Music Assistant, Sonos and Alexa in one
2344-line class body, dispatched by ``if self._platform ==`` in five separate
methods. Its mirror test file is 2787 lines, and a Sonos assertion sat in the
same suite as the Music Assistant confirmation logic — so checking that Sonos
sends one ``play_media`` meant importing the URI cascade, the provider table,
the analytics hook and the queue bookkeeping along with it.

Every test in this file builds ONE strategy over a mock ``hass`` and asserts
against that platform alone. There is no ``MediaPlayerService`` anywhere in the
file, and no game.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.playback import (
    AlexaStrategy,
    MusicAssistantStrategy,
    PlaybackStrategy,
    PlayerContext,
    SonosStrategy,
    build_strategy,
    supported_platforms,
)

SONG = {
    "artist": "Kraftwerk",
    "title": "Das Modell",
    "_resolved_uri": "spotify:track:ABC123",
}


def _hass(queue_response=None) -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock(return_value=queue_response)
    hass.states.get = MagicMock(return_value=None)
    return hass


def _context(hass, platform: str, provider: str = "spotify") -> PlayerContext:
    return PlayerContext(
        hass, "media_player.esszimmer", platform=platform, provider=provider
    )


def _calls(hass) -> list[tuple[str, str]]:
    return [c.args[:2] for c in hass.services.async_call.await_args_list]


class TestTheDispatchHappensInOnePlace:
    """The point of the split: adding a platform touches one table."""

    @pytest.mark.parametrize(
        ("platform", "expected"),
        [
            ("music_assistant", MusicAssistantStrategy),
            ("sonos", SonosStrategy),
            ("alexa_media", AlexaStrategy),
            ("alexa", AlexaStrategy),
        ],
    )
    def test_each_platform_reaches_its_own_strategy(self, platform, expected):
        strategy = build_strategy(_context(_hass(), platform))
        assert isinstance(strategy, expected)

    @pytest.mark.parametrize("platform", ["cast", "unknown", "plex", ""])
    def test_a_platform_beatify_cannot_play_gets_no_strategy(self, platform):
        """Cast without Music Assistant, and anything unrecognised.

        None rather than a raise: the service shell logs "Unsupported platform"
        and returns False, exactly as the old ``if/elif`` chain fell through.
        """
        assert build_strategy(_context(_hass(), platform)) is None

    def test_a_platform_belongs_to_exactly_one_strategy(self):
        """The invariant the old chain could not state: no platform is served
        by two implementations, and none is silently served by none."""
        platforms = supported_platforms()
        assert sorted(platforms) == sorted(set(platforms))
        assert set(platforms) == {"music_assistant", "sonos", "alexa_media", "alexa"}

    def test_every_strategy_answers_the_same_interface(self):
        for platform in supported_platforms():
            strategy = build_strategy(_context(_hass(), platform))
            assert isinstance(strategy, PlaybackStrategy)


class TestSonosOnItsOwn:
    """Sonos, without a line of Music Assistant in the way."""

    @pytest.mark.asyncio
    async def test_it_sends_one_blocking_play_media_with_the_uri(self):
        hass = _hass()
        sonos = SonosStrategy(_context(hass, "sonos"))

        assert await sonos.play(SONG) is True

        assert _calls(hass) == [("media_player", "play_media")]
        call = hass.services.async_call.await_args
        assert call.args[2] == {
            "entity_id": "media_player.esszimmer",
            "media_content_id": "spotify:track:ABC123",
            "media_content_type": "music",
        }
        assert call.kwargs["blocking"] is True

    @pytest.mark.asyncio
    async def test_it_never_touches_the_music_assistant_domain(self):
        """The regression the split is meant to make impossible: a change to
        the Music Assistant path cannot reach this one."""
        hass = _hass()
        await SonosStrategy(_context(hass, "sonos")).play(SONG)

        assert all(domain != "music_assistant" for domain, _ in _calls(hass))

    @pytest.mark.asyncio
    async def test_it_remembers_nothing_of_the_host_queue(self):
        """#2143 is Music Assistant's alone — Sonos cannot report a queue."""
        sonos = SonosStrategy(_context(_hass(), "sonos"))
        assert await sonos.capture_queue() is None


class TestAlexaOnItsOwn:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("provider", "content_type"),
        [
            ("spotify", "SPOTIFY"),
            ("amazon_music", "AMAZON_MUSIC"),
            ("apple_music", "APPLE_MUSIC"),
        ],
    )
    async def test_the_provider_picks_the_content_type(self, provider, content_type):
        hass = _hass()
        alexa = AlexaStrategy(_context(hass, "alexa_media", provider))

        assert await alexa.play(SONG) is True

        assert hass.services.async_call.await_args.args[2] == {
            "entity_id": "media_player.esszimmer",
            "media_content_id": "Das Modell by Kraftwerk",
            "media_content_type": content_type,
        }

    @pytest.mark.asyncio
    async def test_an_unmapped_provider_warns_and_falls_back(self, caplog):
        """#1402: deezer has no Alexa mapping. It must not be silently mapped."""
        hass = _hass()
        alexa = AlexaStrategy(_context(hass, "alexa_media", "deezer"))

        with caplog.at_level("WARNING"):
            await alexa.play(SONG)

        assert "unexpected provider" in caplog.text
        assert "deezer" in caplog.text
        assert (
            hass.services.async_call.await_args.args[2]["media_content_type"]
            == "APPLE_MUSIC"
        )

    def test_only_the_first_of_several_artists_is_spoken(self):
        alexa = AlexaStrategy(_context(_hass(), "alexa_media"))
        text = alexa._get_alexa_search_text({"artist": "A;B", "title": "T"})
        assert text == "T by A"

    @pytest.mark.asyncio
    async def test_it_remembers_nothing_of_the_host_queue(self):
        alexa = AlexaStrategy(_context(_hass(), "alexa_media"))
        assert await alexa.capture_queue() is None


class TestMusicAssistantOnItsOwn:
    """Only the part of Music Assistant that the other two do not have."""

    @pytest.mark.asyncio
    async def test_it_is_the_only_platform_that_reports_a_queue(self):
        """#2143: ``get_queue`` exists in Music Assistant and nowhere else."""
        hass = _hass(
            {
                "media_player.esszimmer": {
                    "current_item": {
                        "media_item": {"uri": "apple_music://track/1", "name": "María"}
                    },
                    "elapsed_time": 42.0,
                    "shuffle_enabled": True,
                    "repeat_mode": "all",
                }
            }
        )
        ma = MusicAssistantStrategy(_context(hass, "music_assistant"))

        assert await ma.capture_queue() == {
            "uri": "apple_music://track/1",
            "name": "María",
            "elapsed_time": 42.0,
            "shuffle": True,
            "repeat_mode": "all",
        }
        assert _calls(hass) == [("music_assistant", "get_queue")]

    @pytest.mark.asyncio
    async def test_an_idle_speaker_reports_an_empty_snapshot_not_none(self):
        """``{}`` and ``None`` are different answers: ``{}`` means "asked, and
        there was nothing", which stops the shell asking again in round two."""
        ma = MusicAssistantStrategy(_context(_hass({}), "music_assistant"))
        assert await ma.capture_queue() == {}

    def test_the_candidate_cascade_stays_inside_the_users_provider(self):
        """#805, checkable without a speaker, a game or the other platforms."""
        ma = MusicAssistantStrategy(_context(_hass(), "music_assistant", "apple_music"))
        candidates = ma.uri_candidates(
            {
                "_resolved_uri": "applemusic://track/1",
                "uri_apple_music": "applemusic://track/2",
                "uri_spotify": "spotify:track:NOPE",
            }
        )
        assert [uri for _, uri in candidates] == [
            "apple_music://track/1",
            "apple_music://track/2",
        ]


class TestTheAttemptRecordIsSharedNotDuplicated:
    """``last_attempted_uri`` / ``last_failure_reason`` are read off the service
    by ``game/state_lifecycle.py``, and written by whichever strategy ran. Both
    sides therefore read one place — the context."""

    def test_what_the_strategy_writes_the_context_reports(self):
        context = _context(_hass(), "sonos")
        strategy = build_strategy(context)

        strategy.last_attempted_uri = "spotify:track:ABC123"
        strategy.last_failure_reason = "unavailable"

        assert context.last_attempted_uri == "spotify:track:ABC123"
        assert context.last_failure_reason == "unavailable"
