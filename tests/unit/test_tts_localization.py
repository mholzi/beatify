"""Tests for localized TTS announcements.

The game's ``language`` setting (en/de/es/fr/nl) used to drive only the web UI;
spoken announcements were hardcoded English. ``game.tts_phrases`` adds per-
language phrase tables and ``GameState`` now renders announcements in the game
language and forwards that language to ``tts.speak`` so multilingual engines use
the matching voice.

The placeholder-fidelity tests are the safety net for the (machine-assisted)
de/es/fr/nl translations: any missing key or drifted ``{placeholder}`` fails CI
rather than silently degrading a live game.
"""

from __future__ import annotations

import asyncio
import string
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game import tts_phrases as tp
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.services.tts import TTSService, _match_language
from tests.conftest import make_game_state

# A superset of every placeholder used by any phrase, so a template renders
# regardless of which slots it uses.
SAMPLE = {
    "rounds": 10,
    "difficulty": "normal",
    "name": "Marco",
    "names": "Marco and Anna",
    "points": 42,
    "round": 3,
    "year": 1991,
    "streak": 5,
    "previous": 4,
    "stealer": "Marco",
    "target": "Anna",
}


def _fields(template: str) -> set[str]:
    """Placeholder names referenced by a str.format template."""
    return {
        name for _, name, _, _ in string.Formatter().parse(template) if name is not None
    }


# ---------------------------------------------------------------------------
# Pack integrity — the translation safety net
# ---------------------------------------------------------------------------


def test_every_language_has_every_phrase_key():
    en_keys = set(tp._PHRASES["en"])
    assert set(tp._PHRASES) == set(tp.SUPPORTED_LANGUAGES)
    for lang, pack in tp._PHRASES.items():
        assert set(pack) == en_keys, f"{lang} phrase keys differ from English"


def test_placeholder_sets_match_english_exactly():
    # Every translated phrase must use the SAME {placeholders} as English —
    # none missing, added, renamed, or with text translated inside the braces.
    for key, en_template in tp._PHRASES["en"].items():
        expected = _fields(en_template)
        for lang in tp.SUPPORTED_LANGUAGES:
            assert _fields(tp._PHRASES[lang][key]) == expected, f"{lang}/{key}"


def test_every_phrase_formats_without_error_or_stray_braces():
    for lang in tp.SUPPORTED_LANGUAGES:
        for key, template in tp._PHRASES[lang].items():
            rendered = template.format(**SAMPLE)
            assert "{" not in rendered and "}" not in rendered, f"{lang}/{key}"


def test_aux_tables_cover_every_language():
    for lang in tp.SUPPORTED_LANGUAGES:
        assert lang in tp._AND
        assert set(tp._DIFFICULTY[lang]) == {"easy", "normal", "hard"}
        assert set(tp._PLACE[lang]) == {1, 2, 3}


# ---------------------------------------------------------------------------
# Helper behaviour
# ---------------------------------------------------------------------------


def test_normalize_language_falls_back_to_english():
    assert tp.normalize_language("de") == "de"
    assert tp.normalize_language("xx") == "en"
    assert tp.normalize_language(None) == "en"
    assert tp.normalize_language("") == "en"


def test_phrase_english_is_byte_identical_to_original():
    # These must match the pre-localization hardcoded strings verbatim.
    assert tp.phrase("en", "time_up") == "Time's up!"
    assert tp.phrase("en", "round_start", round=3) == "Round 3 — get ready!"
    assert tp.phrase("en", "answer", year=1991) == "The answer was 1991."
    assert tp.phrase("en", "countdown") == "Three, two, one — go!"
    assert (
        tp.phrase("en", "game_start", rounds=10, difficulty="normal")
        == "Let's play Beatify! 10 rounds, normal difficulty."
    )


def test_phrase_renders_german():
    assert tp.phrase("de", "time_up") == "Zeit ist um!"
    assert tp.phrase("de", "round_start", round=4) == "Runde 4 — macht euch bereit!"
    assert tp.phrase("de", "answer", year=1991) == "Die Antwort war 1991."


def test_phrase_unknown_language_falls_back_to_english():
    assert tp.phrase("xx", "time_up") == "Time's up!"


def test_phrase_malformed_translation_falls_back_to_english(monkeypatch):
    # A bad translation (stray placeholder) must never crash a live game.
    broken = dict(tp._PHRASES)
    broken["de"] = dict(broken["de"], answer="Antwort {does_not_exist}.")
    monkeypatch.setattr(tp, "_PHRASES", broken)
    assert tp.phrase("de", "answer", year=1991) == "The answer was 1991."


def test_join_names_uses_language_word():
    assert tp.join_names("en", ["Marco"]) == "Marco"
    assert tp.join_names("en", ["Marco", "Anna"]) == "Marco and Anna"
    assert tp.join_names("de", ["Marco", "Anna"]) == "Marco und Anna"
    assert tp.join_names("fr", ["Marco", "Anna"]) == "Marco et Anna"


def test_difficulty_and_place_labels_localized():
    assert tp.difficulty_label("en", "normal") == "normal"
    assert tp.difficulty_label("de", "hard") == "schwer"
    assert tp.difficulty_label("xx", "easy") == "easy"
    assert tp.place_label("en", 1) == "1st place"
    assert tp.place_label("de", 1) == "erster Platz"


def test_spoken_number_english_keeps_digits():
    # English reads digits fine and its strings are pinned — never spell out.
    assert tp.spoken_number("en", 1991, "year") == "1991"
    assert tp.spoken_number("en", 42) == "42"
    assert tp.spoken_number("xx", 1991) == "1991"  # unknown → English/digits


def test_spoken_number_spells_out_non_english():
    assert tp.spoken_number("de", 1991, "year") == "neunzehnhunderteinundneunzig"
    assert tp.spoken_number("de", 42) == "zweiundvierzig"
    assert tp.spoken_number("fr", 1991, "year") == "mille neuf cent quatre-vingt-onze"
    assert tp.spoken_number("es", 2005, "year") == "dos mil cinco"


def test_spoken_number_guards_none_and_float():
    # Defense-in-depth (#1225): a stray None / float must never speak as "None"
    # or a fractional reading. None drops out; a float rounds to a whole number.
    assert tp.spoken_number("de", None) == ""
    assert tp.spoken_number("en", None) == ""
    assert tp.spoken_number("en", 19.0) == "19"
    assert tp.spoken_number("de", 42.4) == "zweiundvierzig"  # rounds, no "Komma"
    assert "," not in tp.spoken_number("de", 19.5)  # never "neunzehn Komma fünf"


# ---------------------------------------------------------------------------
# GameState wiring
# ---------------------------------------------------------------------------


def _player(name, **fields):
    player = PlayerSession(name=name, ws=None)
    for key, value in fields.items():
        setattr(player, key, value)
    return player


@pytest.mark.asyncio
async def test_announce_round_start_localized_german():
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.language = "de"
    state.round = 4
    await state.announce_round_start()
    state._tts_announce.assert_awaited_once_with("Runde vier — macht euch bereit!")


@pytest.mark.asyncio
async def test_announce_round_start_defaults_to_english_when_unset():
    # No language set on the state → English, unchanged behaviour.
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.round = 4
    await state.announce_round_start()
    state._tts_announce.assert_awaited_once_with("Round 4 — get ready!")


@pytest.mark.asyncio
async def test_announce_reveal_localized_german():
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.language = "de"
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=10)}
    await state._announce_reveal(1991)
    spoken = state._tts_announce.await_args.args[0]
    assert "Die Antwort war neunzehnhunderteinundneunzig." in spoken
    assert "Goldrichtig: Marco." in spoken


@pytest.mark.asyncio
async def test_tts_announce_forwards_language_to_speak():
    state = make_game_state()
    svc = MagicMock()
    svc.speak = AsyncMock()
    state._tts_service = svc
    state.language = "de"
    await state._tts_announce("hallo")
    await asyncio.sleep(0)  # let the fire-and-forget task run
    svc.speak.assert_awaited_once_with("hallo", language="de")


# ---------------------------------------------------------------------------
# TTSService language forwarding
# ---------------------------------------------------------------------------


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    def _get(entity_id: str):
        if entity_id.startswith(("tts.", "media_player.")):
            return MagicMock(state="idle")
        return None

    hass.states.get = MagicMock(side_effect=_get)
    return hass


def _payload(hass: MagicMock) -> dict:
    args, kwargs = hass.services.async_call.call_args
    for value in (*args, *kwargs.values()):
        if isinstance(value, dict) and "message" in value:
            return value
    raise AssertionError("no service-data dict with 'message' found")


def test_match_language_exact_then_prefix():
    assert _match_language("de", ["en-US", "de-DE"]) == "de-DE"  # de -> de-DE
    assert _match_language("de", ["de", "en"]) == "de"  # exact wins
    assert _match_language("de", ["DE_DE"]) == "DE_DE"  # case/sep-insensitive
    assert _match_language("de", ["en-US", "fr-FR"]) is None  # unsupported
    assert _match_language("de", None) is None
    assert _match_language("de", []) is None
    assert _match_language(None, ["de-DE"]) is None


@pytest.mark.asyncio
async def test_speak_forwards_resolved_language_when_supported(monkeypatch):
    hass = _make_hass()
    svc = TTSService(hass, "tts.x", "media_player.y")
    monkeypatch.setattr(svc, "_supported_languages", lambda: ["en-US", "de-DE"])
    await svc.speak("hallo", language="de")
    assert _payload(hass)["language"] == "de-DE"


@pytest.mark.asyncio
async def test_speak_omits_language_when_unsupported(monkeypatch):
    hass = _make_hass()
    svc = TTSService(hass, "tts.x", "media_player.y")
    monkeypatch.setattr(svc, "_supported_languages", lambda: ["en-US"])
    await svc.speak("hallo", language="de")
    assert "language" not in _payload(hass)


@pytest.mark.asyncio
async def test_speak_omits_language_when_support_unknown(monkeypatch):
    # Introspection failed (e.g. older HA) → omit rather than force a code.
    hass = _make_hass()
    svc = TTSService(hass, "tts.x", "media_player.y")
    monkeypatch.setattr(svc, "_supported_languages", lambda: None)
    await svc.speak("hallo", language="de")
    assert "language" not in _payload(hass)


@pytest.mark.asyncio
async def test_speak_omits_language_when_not_set():
    hass = _make_hass()
    await TTSService(hass, "tts.x", "media_player.y").speak("hello")
    assert "language" not in _payload(hass)
