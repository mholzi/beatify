"""#2552 and #2554 — telling the right person what just happened.

Both fixes live in static assets, so they are checked against the source the
way #2500's companion test checks the tour strings.

* #2552 — a speaker failure told the room the host had disconnected, while the
  host stood next to the TV, and told the guests to check their own media
  player. ``pause_reason`` was in the state payload the whole time.
* #2554 — the host can stop the song mid-round. Only the host's own button
  changed; to everyone else the music cut out with the timer still running.
"""

from __future__ import annotations

import json
from pathlib import Path

WWW = Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"
LOCALES = ("en", "de", "es", "fr", "it", "nl")
NEW_KEYS = ("pausedSpeaker", "pausedNoSongs", "pausedHintSpeaker", "songStoppedChip")


def _locale(name: str) -> dict:
    return json.loads((WWW / "i18n" / f"{name}.json").read_text(encoding="utf-8"))


class TestPauseReasonReachesTheScreens:
    def test_dashboard_renders_the_paused_view_from_state(self):
        js = (WWW / "js" / "dashboard.js").read_text(encoding="utf-8")
        assert "renderPausedView(state)" in js
        assert "function renderPausedView(state)" in js

    def test_every_pause_reason_has_its_own_message(self):
        js = (WWW / "js" / "dashboard.js").read_text(encoding="utf-8")
        body = js.split("function renderPausedView(state)", 1)[1].split("\n    }", 1)[0]
        assert "media_player_error" in body
        assert "no_songs_available" in body
        assert "game.pausedSpeaker" in body
        assert "game.pausedNoSongs" in body

    def test_the_tv_pause_icon_is_a_glyph_not_two_pipes(self):
        html = (WWW / "dashboard.html").read_text(encoding="utf-8")
        assert '<div class="paused-icon">||</div>' not in html
        assert 'class="paused-icon"' in html

    def test_the_phone_hint_follows_the_reason(self):
        js = (WWW / "js" / "player-end.js").read_text(encoding="utf-8")
        body = js.split("export function updatePausedView", 1)[1].split("\n}", 1)[0]
        assert "game.pausedHintSpeaker" in body
        assert "pause-hint" in body
        assert 'id="pause-hint"' in (WWW / "player.html").read_text(encoding="utf-8")

    def test_guests_are_not_told_to_check_their_own_player(self):
        for name in LOCALES:
            text = _locale(name)["player"]["speakerUnavailable"].lower()
            for phrase in ("your media player", "deinen mediaplayer", "je mediaspeler"):
                assert phrase not in text, f"{name} still blames the guest"


class TestSongStoppedIsAnnounced:
    def test_the_dashboard_no_longer_ignores_the_event(self):
        js = (WWW / "js" / "dashboard.js").read_text(encoding="utf-8")
        assert "data.type === 'song_stopped'" in js
        assert "ignores submit_ack, song_stopped" not in js

    def test_the_chip_is_pinned_to_its_round(self):
        js = (WWW / "js" / "dashboard.js").read_text(encoding="utf-8")
        assert "songStoppedRound" in js
        assert "setSongStoppedChip(false)" in js, "the chip must clear next round"

    def test_the_phone_chip_exists_and_is_tracked(self):
        html = (WWW / "player.html").read_text(encoding="utf-8")
        assert 'id="song-stopped-chip"' in html

        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        row = js.split("function syncArcChipRow()", 1)[1].split("]", 1)[0]
        assert "song-stopped-chip" in row, "chip must count towards row visibility"

        stopped = js.split("export function handleSongStopped()", 1)[1].split("\n}", 1)[
            0
        ]
        assert "song-stopped-chip" in stopped
        reset = js.split("export function resetSongStoppedState()", 1)[1].split(
            "\n}", 1
        )[0]
        assert "song-stopped-chip" in reset


class TestTranslations:
    def test_all_new_keys_exist_in_every_locale(self):
        for name in LOCALES:
            game = _locale(name)["game"]
            for key in NEW_KEYS:
                assert game.get(key), f"{name} is missing game.{key}"
