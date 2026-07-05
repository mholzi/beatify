"""Gameplay guessing WebSocket handlers (#1588 split).

Year submission, steal targeting/execution, and the artist / movie /
title-artist guess + vote + override flows. Extracted verbatim from the former
monolithic ``ws_handlers`` module — behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.const import (
    ARTIST_BONUS_POINTS,
    ERR_ALREADY_SUBMITTED,
    ERR_ELIMINATED,
    ERR_INVALID_ACTION,
    ERR_NO_ARTIST_CHALLENGE,
    ERR_NO_MOVIE_CHALLENGE,
    ERR_NO_TITLE_ARTIST_CHALLENGE,
    ERR_NOT_ADMIN,
    ERR_NOT_IN_GAME,
    ERR_ROUND_EXPIRED,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.state import GamePhase, GameState

if TYPE_CHECKING:
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


async def handle_submit(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle guess submission from player."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: a Sudden Death eliminated player is out of the game — reject any
    # server-side guess so a stale client can't keep banking score.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Not in playing phase",
            }
        )
        return

    if player.submitted:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ALREADY_SUBMITTED,
                "message": "Already submitted",
            }
        )
        return

    if game_state.is_deadline_passed():
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            }
        )
        return

    year = data.get("year")
    if not isinstance(year, int) or year < YEAR_MIN or year > YEAR_MAX:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid year",
            }
        )
        return

    bet = data.get("bet", False)
    player.bet = bool(bet)

    submission_time = game_state.current_time()
    player.submit_guess(year, submission_time)

    await ws.send_json(
        {
            "type": "submit_ack",
            "year": year,
        }
    )

    # Issue #581: Only broadcast here when NOT all guesses are complete.
    # If all guesses are in, trigger_early_reveal_if_complete() will
    # transition to REVEAL and broadcast via the round_end callback,
    # avoiding a redundant double broadcast.
    if not game_state.check_all_guesses_complete():
        # #1763: in-round submit progress → debounce (coalesces the per-player
        # burst); the completing submit skips this and phase-transitions below.
        await handler.debounced_broadcast_state()

    _LOGGER.debug(
        "Early reveal check: phase=%s, artist_challenge=%s",
        game_state.phase.value,
        game_state.artist_challenge_enabled,
    )
    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.info(
        "Player %s submitted guess: %d at %.2f", player.name, year, submission_time
    )


async def handle_get_steal_targets(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle request for available steal targets (Story 15.3 AC2, AC5)."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: an eliminated player (Sudden Death) may not use a banked steal.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    if not player.steal_available:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "No steal available",
            }
        )
        return

    targets = game_state.get_steal_targets(player.name)
    await ws.send_json(
        {
            "type": "steal_targets",
            "targets": targets,
        }
    )


async def handle_steal(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle steal execution (Story 15.3 AC2, AC3)."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: an eliminated player (Sudden Death) may not execute a banked steal.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    target_name = data.get("target")
    if not target_name:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Target name required",
            }
        )
        return

    result = game_state.use_steal(player.name, target_name)

    if result["success"]:
        await ws.send_json(
            {
                "type": "steal_ack",
                "success": True,
                "target": result["target"],
                "year": result["year"],
            }
        )
        # Issue #842 Phase 4: announce the steal (use case 23).
        await game_state.announce_steal_used(player.name, result["target"])
        if not game_state.check_all_guesses_complete():
            # #1763: in-round progress → debounce.
            await handler.debounced_broadcast_state()
        await game_state.trigger_early_reveal_if_complete()
    else:
        await ws.send_json(
            {
                "type": "error",
                "code": result["error"],
                "message": _get_steal_error_message(result["error"]),
            }
        )


def _get_steal_error_message(error_code: str) -> str:
    """Get human-readable message for steal error codes."""
    messages = {
        ERR_NOT_IN_GAME: "Not in game",
        ERR_INVALID_ACTION: "Cannot steal now",
        "NO_STEAL_AVAILABLE": "No steal available",
        "TARGET_NOT_SUBMITTED": "Target has not submitted yet",
        "CANNOT_STEAL_SELF": "Cannot steal from yourself",
    }
    return messages.get(error_code, "Steal failed")


async def handle_artist_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle artist guess submission (Story 20.3)."""
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only guess during PLAYING phase",
            }
        )
        return

    # #1662: reject late guesses in the window between deadline expiry and the
    # end_round phase flip — mirrors the year handler's guard so Artist/Movie/
    # Title&Artist challenges can't bank points/bonus after time is up.
    if game_state.is_deadline_passed():
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: reject guesses from a Sudden Death eliminated player.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    if not game_state.artist_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_ARTIST_CHALLENGE,
                "message": "No artist challenge this round",
            }
        )
        return

    # One artist attempt per player per round. The artist challenge is
    # multiple-choice and the options are broadcast, so without this guard a
    # player could submit each option in turn and is guaranteed to hit the
    # correct one (brute-force the bonus). Unlike the movie flow,
    # ``submit_artist_guess`` only dedupes the *global* winner, not per-player
    # attempts — so the lock has to live here. (#1660)
    if player.has_artist_guess:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Artist already guessed this round",
            }
        )
        return

    artist = data.get("artist", "").strip()
    if not artist:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Artist cannot be empty",
            }
        )
        return

    guess_time = game_state.current_time()
    result = game_state.submit_artist_guess(player.name, artist, guess_time)
    player.has_artist_guess = True

    response: dict = {
        "type": "artist_guess_ack",
        "correct": result["correct"],
    }

    if result["correct"]:
        response["first"] = result["first"]
        if result["first"]:
            response["bonus_points"] = ARTIST_BONUS_POINTS
        else:
            response["winner"] = result["winner"]

    await ws.send_json(response)

    if result.get("first"):
        # #1763: in-round progress (first-correct flag) → debounce.
        await handler.debounced_broadcast_state()

    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Artist guess from %s: '%s' -> correct=%s, first=%s",
        player.name,
        artist,
        result["correct"],
        result.get("first", False),
    )


async def handle_movie_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle movie quiz guess submission (Issue #28)."""
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only guess during PLAYING phase",
            }
        )
        return

    # #1662: reject late guesses in the window between deadline expiry and the
    # end_round phase flip — mirrors the year handler's guard so Artist/Movie/
    # Title&Artist challenges can't bank points/bonus after time is up.
    if game_state.is_deadline_passed():
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: reject guesses from a Sudden Death eliminated player.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    if not game_state.movie_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_MOVIE_CHALLENGE,
                "message": "No movie quiz this round",
            }
        )
        return

    movie = data.get("movie", "").strip()
    if not movie:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Movie cannot be empty",
            }
        )
        return

    guess_time = game_state.current_time()
    result = game_state.submit_movie_guess(player.name, movie, guess_time)
    player.has_movie_guess = True

    response: dict = {
        "type": "movie_guess_ack",
        "correct": result["correct"],
        "already_guessed": result["already_guessed"],
    }

    if result["correct"] and not result["already_guessed"]:
        response["rank"] = result["rank"]
        response["bonus"] = result["bonus"]

    await ws.send_json(response)
    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Movie guess from %s: '%s' -> correct=%s, rank=%s",
        player.name,
        movie,
        result["correct"],
        result.get("rank"),
    )


async def handle_title_artist_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a title & artist guess submission (#1180).

    Mirrors handle_artist_guess: phase-gated to PLAYING, classifies the
    submitted title and artist independently via the challenge, acks the
    per-field status, marks the player done, and triggers early reveal once
    everyone has guessed. Empty fields are allowed — they classify as
    "skipped" (0 points for that field), so they are NOT rejected here.
    """
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only guess during PLAYING phase",
            }
        )
        return

    # #1662: reject late guesses in the window between deadline expiry and the
    # end_round phase flip — mirrors the year handler's guard so Artist/Movie/
    # Title&Artist challenges can't bank points/bonus after time is up.
    if game_state.is_deadline_passed():
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    # #1748: reject guesses from a Sudden Death eliminated player.
    if player.eliminated:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ELIMINATED,
                "message": "You have been eliminated",
            }
        )
        return

    if not game_state.title_artist_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_TITLE_ARTIST_CHALLENGE,
                "message": "No title & artist challenge this round",
            }
        )
        return

    title = data.get("title", "")
    artist = data.get("artist", "")
    if not isinstance(title, str):
        title = ""
    if not isinstance(artist, str):
        artist = ""
    # Guess length is capped at the WS ingest boundary (#1581) before dispatch,
    # so title/artist already fit MAX_GUESS_LEN here. classify_field truncates
    # again defensively.

    guess_time = game_state.current_time()
    result = game_state.submit_title_artist_guess(
        player.name, title, artist, guess_time
    )
    player.has_title_artist_guess = True
    # Mark the player as submitted so the round behaves like a normal
    # submission (#1180): ScoringService.score_player_round gates the
    # title/artist points path on ``player.submitted``, and all_submitted() /
    # check_all_guesses_complete() rely on it for early reveal. There is no
    # year in this mode, so we set the submission state directly rather than
    # going through player.submit_guess (which expects a year).
    player.submitted = True
    player.submission_time = guess_time

    await ws.send_json(
        {
            "type": "title_artist_guess_ack",
            "title_status": result["title_status"],
            "artist_status": result["artist_status"],
        }
    )

    # Mirror handle_artist_guess / handle_submit: avoid a redundant broadcast
    # when the early-reveal path is about to broadcast via the round_end
    # callback. Only broadcast here when the round is NOT yet complete.
    if not game_state.check_all_guesses_complete():
        # #1763: in-round progress → debounce.
        await handler.debounced_broadcast_state()

    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Title/artist guess from %s: title=%r (%s), artist=%r (%s)",
        player.name,
        title,
        result["title_status"],
        artist,
        result["artist_status"],
    )


async def handle_title_artist_vote(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a community vote on a title/artist near-miss (#1180 Phase 4).

    REVEAL-only. A player may not vote on their own near-miss (the near-miss
    player is encoded as the prefix of nearmiss_id, "player:field").
    """
    if game_state.phase != GamePhase.REVEAL:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only vote during REVEAL phase",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    nearmiss_id = data.get("nearmiss_id")
    accept = data.get("accept")
    if not isinstance(nearmiss_id, str) or ":" not in nearmiss_id:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid nearmiss_id",
            }
        )
        return
    if not isinstance(accept, bool):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid vote value",
            }
        )
        return

    # #1180: only accept votes for a real, vote-eligible near-miss. Without this
    # the votes dict would store an entry for ANY string, letting a player flood
    # it with fabricated ids during REVEAL and exhaust server memory.
    if nearmiss_id not in {nm["id"] for nm in game_state.get_near_misses()}:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Unknown nearmiss_id",
            }
        )
        return

    # Reject self-vote: the near-miss player is the part before the last ":".
    nearmiss_player = nearmiss_id.rsplit(":", 1)[0]
    if nearmiss_player == player.name:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot vote on your own guess",
            }
        )
        return

    game_state.register_title_artist_vote(player.name, nearmiss_id, accept)
    _LOGGER.debug(
        "Title/artist vote by %s on %s -> %s", player.name, nearmiss_id, accept
    )
    # #1763: REVEAL-phase vote tallies are the same per-player burst as guesses
    # — coalesce them through the debounce rather than a full frame per vote.
    await handler.debounced_broadcast_state()


async def handle_title_artist_override(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a host override on a title/artist near-miss (#1180 Phase 4).

    REVEAL-only, admin-only. Override precedence is applied at resolve time
    (window expiry or host-advance) by resolve_title_artist.
    """
    if game_state.phase != GamePhase.REVEAL:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only override during REVEAL phase",
            }
        )
        return

    is_admin_ws = game_state._admin_ws is not None and game_state._admin_ws is ws
    sender = game_state.get_player_by_ws(ws)
    if not (is_admin_ws or (sender and sender.is_admin)):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_ADMIN,
                "message": "Only admin can override",
            }
        )
        return

    nearmiss_id = data.get("nearmiss_id")
    accept = data.get("accept")
    if not isinstance(nearmiss_id, str) or ":" not in nearmiss_id:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid nearmiss_id",
            }
        )
        return
    if not isinstance(accept, bool):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid override value",
            }
        )
        return

    # #1180: only accept overrides for a real, vote-eligible near-miss (mirrors
    # the vote handler) so the overrides dict can't be grown with fake ids.
    if nearmiss_id not in {nm["id"] for nm in game_state.get_near_misses()}:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Unknown nearmiss_id",
            }
        )
        return

    game_state.set_title_artist_override(nearmiss_id, accept)
    _LOGGER.info("Title/artist override on %s -> %s", nearmiss_id, accept)
    # #1763: an override is a non-phase-changing in-round tally update — debounce.
    await handler.debounced_broadcast_state()
