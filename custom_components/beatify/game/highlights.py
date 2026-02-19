"""Game highlights tracking for Beatify (Issue #75).

Records notable moments during gameplay for an end-of-game highlights reel.
Read-only tracking — does not modify scoring or game mechanics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# Priority weights for ranking highlights
_PRIORITY: dict[str, int] = {
    "exact_match": 3,
    "streak": 4,
    "bet_win": 3,
    "heartbreaker": 5,
    "speed_record": 2,
    "comeback": 4,
    "photo_finish": 5,
}

_EMOJI: dict[str, str] = {
    "exact_match": "🎯",
    "streak": "🔥",
    "bet_win": "🎰",
    "heartbreaker": "💔",
    "speed_record": "⚡",
    "comeback": "🚀",
    "photo_finish": "📸",
}


@dataclass
class GameHighlight:
    """A single notable moment from the game."""

    type: str
    round: int
    player: str
    description: str  # i18n key
    description_params: dict = field(default_factory=dict)
    emoji: str = ""
    score_impact: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "type": self.type,
            "round": self.round,
            "player": self.player,
            "description": self.description,
            "description_params": self.description_params,
            "emoji": self.emoji,
            "score_impact": self.score_impact,
        }


class HighlightsTracker:
    """Collects and ranks game highlights."""

    def __init__(self) -> None:
        self._highlights: list[GameHighlight] = []

    def record_event(self, highlight: GameHighlight) -> None:
        """Record a generic highlight event."""
        self._highlights.append(highlight)

    def record_exact_match(
        self, player_name: str, song_title: str, year: int, round_num: int
    ) -> None:
        """Record an exact year match."""
        self.record_event(
            GameHighlight(
                type="exact_match",
                round=round_num,
                player=player_name,
                description="highlight_exact_match",
                description_params={
                    "player": player_name,
                    "song": song_title,
                    "year": str(year),
                },
                emoji=_EMOJI["exact_match"],
                score_impact=10,
            )
        )

    def record_streak(
        self, player_name: str, streak_count: int, round_num: int
    ) -> None:
        """Record a streak milestone (3, 5, 7+)."""
        self.record_event(
            GameHighlight(
                type="streak",
                round=round_num,
                player=player_name,
                description="highlight_streak",
                description_params={
                    "player": player_name,
                    "count": str(streak_count),
                },
                emoji=_EMOJI["streak"],
                score_impact=0,
            )
        )

    def record_bet_win(
        self, player_name: str, points_gained: int, round_num: int
    ) -> None:
        """Record a successful bet with significant payoff."""
        self.record_event(
            GameHighlight(
                type="bet_win",
                round=round_num,
                player=player_name,
                description="highlight_bet_win",
                description_params={
                    "player": player_name,
                    "points": str(points_gained),
                },
                emoji=_EMOJI["bet_win"],
                score_impact=points_gained,
            )
        )

    def record_heartbreaker(
        self, player_name: str, song_title: str, years_off: int, round_num: int
    ) -> None:
        """Record a near-miss (off by 1 year)."""
        self.record_event(
            GameHighlight(
                type="heartbreaker",
                round=round_num,
                player=player_name,
                description="highlight_heartbreaker",
                description_params={
                    "player": player_name,
                    "song": song_title,
                    "years_off": str(years_off),
                },
                emoji=_EMOJI["heartbreaker"],
                score_impact=0,
            )
        )

    def record_speed_record(
        self, player_name: str, time_seconds: float, round_num: int
    ) -> None:
        """Record the fastest submission in a round."""
        self.record_event(
            GameHighlight(
                type="speed_record",
                round=round_num,
                player=player_name,
                description="highlight_speed_record",
                description_params={
                    "player": player_name,
                    "time": str(round(time_seconds, 1)),
                },
                emoji=_EMOJI["speed_record"],
                score_impact=0,
            )
        )

    def record_comeback(
        self, player_name: str, positions_gained: int, round_num: int
    ) -> None:
        """Record a significant rank improvement."""
        self.record_event(
            GameHighlight(
                type="comeback",
                round=round_num,
                player=player_name,
                description="highlight_comeback",
                description_params={
                    "player": player_name,
                    "positions": str(positions_gained),
                },
                emoji=_EMOJI["comeback"],
                score_impact=0,
            )
        )

    def record_photo_finish(
        self, player_names: list[str], round_num: int
    ) -> None:
        """Record tied scores between players."""
        self.record_event(
            GameHighlight(
                type="photo_finish",
                round=round_num,
                player=player_names[0] if player_names else "",
                description="highlight_photo_finish",
                description_params={
                    "round": str(round_num),
                    "players": ", ".join(player_names),
                },
                emoji=_EMOJI["photo_finish"],
                score_impact=0,
            )
        )

    def get_top_highlights(self, limit: int = 8) -> list[GameHighlight]:
        """Return the most interesting highlights, ranked by priority."""
        # Sort by priority (descending), then by round (ascending) for chronological tiebreak
        sorted_highlights = sorted(
            self._highlights,
            key=lambda h: (-_PRIORITY.get(h.type, 1), h.round),
        )
        return sorted_highlights[:limit]

    def to_dict(self) -> list[dict]:
        """Convert top highlights to JSON-serializable list for get_state()."""
        return [h.to_dict() for h in self.get_top_highlights()]

    def reset(self) -> None:
        """Clear all recorded highlights."""
        self._highlights.clear()
