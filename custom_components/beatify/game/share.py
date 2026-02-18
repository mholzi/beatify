"""Shareable result cards for Beatify (Issue #120).

Generates Wordle-style emoji grids and share data for end-of-game sharing.
Read-only — does not modify scoring or game mechanics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .player import PlayerSession

# Emoji mapping for round results
_RESULT_EMOJI: dict[str, str] = {
    "exact": "🟣",
    "scored": "🟢",
    "close": "🟡",
    "missed": "🔴",
}


def build_emoji_grid(player: PlayerSession, playlist_name: str, total_rounds: int) -> str:
    """Build Wordle-style emoji grid for text sharing.

    Args:
        player: PlayerSession with round_results populated
        playlist_name: Display name of the playlist
        total_rounds: Total rounds played in the game

    Returns:
        Formatted text string ready for clipboard/sharing

    """
    # Build emoji row from round results
    emoji_row = "".join(_RESULT_EMOJI.get(r, "⬜") for r in player.round_results)

    # Count stats
    scored_count = sum(1 for r in player.round_results if r in ("exact", "scored", "close"))
    exact_count = sum(1 for r in player.round_results if r == "exact")

    lines = [
        f"🎵 Beatify — {playlist_name}",
        f"👑 {player.name}: {player.score}pts",
        "",
        emoji_row,
        f"  {scored_count}/{total_rounds} correct | 🔥 Best Streak: {player.best_streak}",
        "",
        f"🎯 {exact_count} Exact | 💰 {player.bets_won}/{player.bets_placed} Bets",
        "",
        "beatify.fun",
    ]

    return "\n".join(lines)


def build_share_data(game_state: Any) -> dict[str, Any]:
    """Build complete share data for all players.

    Args:
        game_state: GameState instance with players and game info

    Returns:
        Dict with emoji_grids (per player name), playlist_name, total_rounds

    """
    # Extract playlist name
    playlist_name = "Unknown Playlist"
    if game_state.playlists:
        playlist_path = game_state.playlists[0]
        if "/" in playlist_path:
            playlist_name = playlist_path.split("/")[-1].replace(".json", "").replace("-", " ").title()
        else:
            playlist_name = playlist_path.replace(".json", "").replace("-", " ").title()

    total_rounds = game_state.round

    emoji_grids: dict[str, str] = {}
    for name, player in game_state.players.items():
        emoji_grids[name] = build_emoji_grid(player, playlist_name, total_rounds)

    return {
        "emoji_grids": emoji_grids,
        "playlist_name": playlist_name,
        "total_rounds": total_rounds,
    }
