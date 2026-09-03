"""#2551, #2553 and #2557 — the host's phone, and what it tells everyone.

* #2551 — a host who joined from their phone had no way out of a paused game,
  and a refused game start left the button on "Starting..." with the reason
  written onto a hidden element.
* #2553 — errors raised during a round reached guests as the server's English
  prose. Same class as #2532, for everything after the join.
* #2557 — the volume buttons assumed 0.5 because no level ever reached the
  client.
"""

from __future__ import annotations

import json
from pathlib import Path

BEATIFY = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"
WWW = BEATIFY / "www"
LOCALES = ("en", "de", "es", "fr", "it", "nl")

# Every code the guessing / powerup handlers can answer with mid-round.
IN_ROUND_CODES = (
    "FROZEN",
    "ELIMINATED",
    "NO_STEAL_AVAILABLE",
    "CANNOT_STEAL_SELF",
    "NO_SABOTAGE_AVAILABLE",
    "CANNOT_SABOTAGE_SELF",
    "TARGET_NOT_SUBMITTED",
    "TARGET_ALREADY_SUBMITTED",
    "NO_ARTIST_CHALLENGE",
    "NO_MOVIE_CHALLENGE",
    "NO_TITLE_ARTIST_CHALLENGE",
    "INTERNAL_ERROR",
)


def _locale(name: str) -> dict:
    return json.loads((WWW / "i18n" / f"{name}.json").read_text(encoding="utf-8"))


class TestInRoundErrorsAreTranslated:
    def test_the_server_message_is_only_a_fallback(self):
        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        body = js.split("export function handleSubmitError", 1)[1].split("\n}", 1)[0]
        assert "data.message || 'Submission failed'" not in body
        assert "errorText(data)" in body

        helper = js.split("function errorText(data)", 1)[1].split("\n}", 1)[0]
        assert "'errors.' + code" in helper, "must look the code up first"
        assert "data.message" in helper, "server text stays as a fallback"

    def test_every_in_round_code_is_translated(self):
        for name in LOCALES:
            errors = _locale(name)["errors"]
            missing = [c for c in IN_ROUND_CODES if not errors.get(c)]
            assert missing == [], f"{name} is missing {missing}"

    def test_the_button_label_follows_the_game_mode(self):
        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        body = js.split("export function showSubmitError", 1)[1].split("\n}", 1)[0]
        assert "titleArtist.submitGuess" in body

    def test_name_validation_is_translated(self):
        js = (WWW / "js" / "player-utils.js").read_text(encoding="utf-8")
        body = js.split("export function validateName", 1)[1].split("\n}", 1)[0]
        assert "'Please enter a name'" in body, "kept only as a fallback"
        assert "errors.nameEmpty" in body
        assert "errors.nameTooLong" in body
        for name in LOCALES:
            errors = _locale(name)["errors"]
            assert errors.get("nameEmpty")
            assert "{max}" in errors.get("nameTooLong", "")


class TestHostCanLeaveAPausedGame:
    def test_the_paused_view_carries_admin_actions(self):
        html = (WWW / "player.html").read_text(encoding="utf-8")
        paused = html.split('id="paused-view"', 1)[1].split(
            "</div>\n        </div>", 1
        )[0]
        assert 'id="paused-admin-actions"' in paused
        assert 'id="paused-resume-btn"' in paused
        assert 'id="paused-end-btn"' in paused
        assert "/beatify/admin" in paused

    def test_resume_is_wired_to_the_server_action(self):
        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        body = js.split("function handleResumeGame()", 1)[1].split("\n}", 1)[0]
        assert "'resume_game'" in body

    def test_the_paused_branch_renders_them(self):
        js = (WWW / "js" / "player-core.js").read_text(encoding="utf-8")
        assert "renderPausedAdminActions()" in js

    def test_the_actions_are_admin_only(self):
        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        body = js.split("export function renderPausedAdminActions()", 1)[1].split(
            "\n}", 1
        )[0]
        assert "state.isAdmin" in body

    def test_a_failed_start_is_handled_in_the_lobby(self):
        js = (WWW / "js" / "player-lobby.js").read_text(encoding="utf-8")
        assert "export function handleStartFailure" in js
        body = js.split("export function handleStartFailure", 1)[1].split(
            "\nexport ", 1
        )[0]
        assert "start-game-btn" in body, "the button must come back from Starting..."
        assert "showToast" in body, "the reason must be visible"

        core = (WWW / "js" / "player-core.js").read_text(encoding="utf-8")
        assert "handleStartFailure(data)" in core

    def test_both_labels_are_translated(self):
        for name in LOCALES:
            admin = _locale(name)["admin"]
            assert admin.get("resumeGame"), f"{name} is missing admin.resumeGame"
            assert admin.get("openAdminPage"), f"{name} is missing admin.openAdminPage"


class TestVolumeIsKnownNotAssumed:
    def test_the_state_payload_carries_the_level(self):
        py = (BEATIFY / "game" / "serializers.py").read_text(encoding="utf-8")
        assert 'state["volume_level"] = gs.current_volume()' in py

    def test_current_volume_reads_through_to_the_player(self):
        py = (BEATIFY / "game" / "state_media.py").read_text(encoding="utf-8")
        body = py.split("def current_volume(self)", 1)[1].split("\n    def ", 1)[0]
        assert "self._media_player_service.get_volume()" in body

    def test_the_client_adopts_it(self):
        js = (WWW / "js" / "player-game.js").read_text(encoding="utf-8")
        body = js.split("export function syncVolumeFromState(data)", 1)[1].split(
            "\n}", 1
        )[0]
        assert "data.volume_level" in body
        assert "currentVolume" in body
        assert "updateVolumeLimitStates" in body, "the limit guard must follow too"

        core = (WWW / "js" / "player-core.js").read_text(encoding="utf-8")
        assert core.count("syncVolumeFromState(data)") >= 2, "PLAYING and REVEAL"

    def test_the_readout_is_always_on_screen(self):
        html = (WWW / "player.html").read_text(encoding="utf-8")
        assert 'id="volume-readout"' in html
        css = (WWW / "css" / "styles.css").read_text(encoding="utf-8")
        assert ".control-volume-readout" in css
