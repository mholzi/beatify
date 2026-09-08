"""Ghost League — Ausgeschiedene raten weiter, in ihrer eigenen Liga (#2559).

Das Issue nennt das Loch beim Namen: in einem 20-Runden-Sudden-Death sitzt
jemand, der in Runde 2 ausscheidet, **achtzehn Runden** vor „Watching from the
sidelines". Das ist das groesste Leerloch, das sich das Spiel selbst baut.

Das Design-Gate zeichnete vier Varianten, Markus waehlte **B — Ghost League**:
eigene Punkte, eigener Rang, ein Best-Ghost-Award am Ende, und auf dem
Fernseher ein zweiter Block unter den Lebenden, ausdruecklich beschriftet mit
„eigene Punkte, kein Einfluss auf das Spiel".

**Die riskante Stelle benennt das Issue selbst**: der #1748-Riegel existiert,
damit ein veralteter Client nicht weiterpunkten kann — Geisterpunkte duerfen
also nachweislich keine der 45 ``player.score``-Stellen erreichen. Genau das
pruefen die Tests der ersten Klasse, und zwar nicht am Riegel, sondern am
Ergebnis.

**Die Ungerechtigkeit der gewaehlten Variante ist bekannt und beziffert**: wer
frueh ausscheidet, spielt mehr Geisterrunden. Der Award rechnet deshalb pro
gespielter Runde, mit einer Mindestteilnahme. Beides steht in der zweiten
Klasse.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.scoring import (
    MIN_GHOST_ROUNDS_FOR_AWARD,
    ScoringService,
    score_ghost_round,
)
from custom_components.beatify.game.state import GameState

from tests.conftest import make_game_state


def _songs(n: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


@pytest.fixture
def game() -> GameState:
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(sudden_death_mode=True),
    )
    return state


def _seat(state: GameState, name: str):
    ok, _ = state.add_player(name, ws=None)
    assert ok, name
    return state.get_player(name)


def _guess(player, year: int, at: float = 5.0) -> None:
    """Eine abgegebene Schaetzung, so wie der Submit-Pfad sie hinterlaesst."""
    player.submitted = True
    player.current_guess = year
    player.submission_time = at


class TestGhostPointsNeverReachTheLivingGame:
    def test_a_ghost_guess_fills_only_the_ghost_bucket(self, game: GameState):
        ghost = _seat(game, "Tom")
        ghost.eliminated = True
        ghost.eliminated_round = 2
        ghost.score = 480
        _guess(ghost, 1985)

        punkte = score_ghost_round(
            ghost,
            correct_year=1985,
            round_start_time=0.0,
            round_duration=30.0,
            difficulty="normal",
        )

        assert punkte > 0
        assert ghost.ghost_score == punkte
        assert ghost.ghost_rounds == 1
        # Die Zusage des #1748-Riegels, am Ergebnis geprueft statt am Riegel.
        assert ghost.score == 480
        assert ghost.round_scores == []
        assert ghost.streak == 0

    def test_the_round_scoring_pass_routes_a_ghost_here_and_nowhere_else(
        self, game: GameState
    ):
        lebend = _seat(game, "Mara")
        ghost = _seat(game, "Tom")
        ghost.eliminated = True
        ghost.eliminated_round = 2
        _guess(lebend, 1985)
        _guess(ghost, 1985)
        game.round_start_time = 0.0
        game.round_duration = 30.0

        game._score_all_players(
            correct_year=1985, all_players=list(game.players.values())
        )

        assert lebend.score > 0  # der Lebende punktet normal
        assert ghost.score == 0  # der Geist nicht
        assert ghost.ghost_score > 0  # sondern hier
        assert ghost.ghost_rounds == 1

    def test_a_playoff_spectator_is_not_a_ghost(self, game: GameState):
        # Er ist naechste Runde wieder dabei und hat keine eigene Liga; ein
        # Punkt fuer eine Runde, die er ausdruecklich aussetzt, waere falsch.
        zuschauer = _seat(game, "Kim")
        zuschauer.playoff_spectator = True
        _guess(zuschauer, 1985)
        game.round_start_time = 0.0
        game.round_duration = 30.0

        game._score_all_players(
            correct_year=1985, all_players=list(game.players.values())
        )

        assert zuschauer.ghost_score == 0
        assert zuschauer.ghost_rounds == 0
        assert zuschauer.score == 0

    def test_without_sudden_death_nobody_becomes_a_ghost(self):
        state = make_game_state()
        state.create_game(
            playlists=["test.json"],
            songs=_songs(),
            media_player="media_player.party",
            base_url="http://localhost:8123",
            options=GameOptions(),
        )
        ghost = _seat(state, "Tom")
        ghost.eliminated = True
        _guess(ghost, 1985)
        state.round_start_time = 0.0
        state.round_duration = 30.0

        state._score_all_players(
            correct_year=1985, all_players=list(state.players.values())
        )

        assert ghost.ghost_score == 0

    def test_a_silent_ghost_scores_nothing_and_counts_no_round(self, game: GameState):
        # Die Zahl, auf die der Award geht, ist ein Schnitt — wer das Handy
        # weglegt, darf sich damit nicht selbst verduennen und auch nicht
        # profitieren.
        ghost = _seat(game, "Ida")
        ghost.eliminated = True
        punkte = score_ghost_round(
            ghost, correct_year=1985, round_start_time=0.0, round_duration=30.0
        )
        assert punkte == 0
        assert ghost.ghost_rounds == 0

    def test_a_ghost_never_wins_closest_wins(self, game: GameState):
        # `apply_closest_wins` filtert out_of_play — der Geist darf den Topf
        # der Lebenden nicht betreten, auch nicht als Vergleichswert.
        lebend = _seat(game, "Mara")
        ghost = _seat(game, "Tom")
        ghost.eliminated = True
        _guess(lebend, 1990)  # 5 daneben
        _guess(ghost, 1985)  # exakt — und trotzdem irrelevant
        lebend.round_score = 12
        ghost.round_score = 99

        ScoringService.apply_closest_wins(
            list(game.players.values()), correct_year=1985
        )

        # Der Lebende ist der beste ueberlebende Tipp und behaelt seine Punkte.
        assert lebend.round_score == 12


class TestBestGhostIsScoredPerRound:
    def test_the_award_goes_to_the_better_average_not_the_bigger_sum(
        self, game: GameState
    ):
        # Der Fall, den der Entwurf selbst als Schwaeche notiert: Tom flog in
        # Runde 2 raus und spielte fuenf Geisterrunden, Kim in Runde 6 und
        # spielte zwei. Roh gewinnt Tom mit 340 zu 200 — pro Runde ist Kim mit
        # 100 klar besser, und sie bekommt die Karte.
        tom = _seat(game, "Tom")
        tom.eliminated, tom.eliminated_round = True, 2
        tom.ghost_score, tom.ghost_rounds = 340, 5
        kim = _seat(game, "Kim")
        kim.eliminated, kim.eliminated_round = True, 6
        kim.ghost_score, kim.ghost_rounds = 200, 2

        awards = ScoringService.calculate_superlatives(
            list(game.players.values()), rounds_played=8, sudden_death_mode_enabled=True
        )
        ghost_award = next((a for a in awards if a["id"] == "best_ghost"), None)
        assert ghost_award is not None
        assert ghost_award["player_name"] == "Kim"
        assert ghost_award["value"] == 100.0
        assert ghost_award["value_label"] == "ghost_avg"

    def test_one_lucky_round_does_not_win_it(self, game: GameState):
        # Ohne Mindestteilnahme haette ein Geist mit einer einzigen perfekten
        # Runde den perfekten Schnitt — und die Karte.
        gluecklich = _seat(game, "Ida")
        gluecklich.eliminated, gluecklich.eliminated_round = True, 9
        gluecklich.ghost_score, gluecklich.ghost_rounds = 20, 1
        fleissig = _seat(game, "Tom")
        fleissig.eliminated, fleissig.eliminated_round = True, 2
        fleissig.ghost_score, fleissig.ghost_rounds = 100, 5

        awards = ScoringService.calculate_superlatives(
            list(game.players.values()),
            rounds_played=10,
            sudden_death_mode_enabled=True,
        )
        ghost_award = next((a for a in awards if a["id"] == "best_ghost"), None)
        assert ghost_award is not None
        assert ghost_award["player_name"] == "Tom"
        assert MIN_GHOST_ROUNDS_FOR_AWARD == 2

    def test_no_award_without_sudden_death(self, game: GameState):
        tom = _seat(game, "Tom")
        tom.eliminated = True
        tom.ghost_score, tom.ghost_rounds = 340, 5
        awards = ScoringService.calculate_superlatives(
            list(game.players.values()),
            rounds_played=8,
            sudden_death_mode_enabled=False,
        )
        assert not any(a["id"] == "best_ghost" for a in awards)

    def test_no_award_when_nobody_played_as_a_ghost(self, game: GameState):
        _seat(game, "Mara")
        awards = ScoringService.calculate_superlatives(
            list(game.players.values()), rounds_played=8, sudden_death_mode_enabled=True
        )
        assert not any(a["id"] == "best_ghost" for a in awards)


class TestTheLeagueTable:
    def test_it_ranks_by_ghost_points_and_carries_what_the_tv_shows(
        self, game: GameState
    ):
        tom = _seat(game, "Tom")
        tom.eliminated, tom.eliminated_round = True, 2
        tom.ghost_score, tom.ghost_rounds = 340, 5
        kim = _seat(game, "Kim")
        kim.eliminated, kim.eliminated_round = True, 4
        kim.ghost_score, kim.ghost_rounds = 255, 3

        liga = game.ghost_league()

        assert [g["name"] for g in liga] == ["Tom", "Kim"]
        assert liga[0]["rank"] == 1
        assert liga[0]["eliminated_round"] == 2
        assert liga[0]["ghost_rounds"] == 5
        assert liga[0]["schnitt"] == 68.0

    def test_the_living_are_not_in_it(self, game: GameState):
        _seat(game, "Mara")
        tom = _seat(game, "Tom")
        tom.eliminated, tom.eliminated_round = True, 2
        tom.ghost_score, tom.ghost_rounds = 40, 1

        assert [g["name"] for g in game.ghost_league()] == ["Tom"]

    def test_a_ghost_who_never_guessed_is_not_in_it(self, game: GameState):
        # Sonst stuende jemand mit 0 gp in einer Tabelle, an der er nicht
        # teilgenommen hat — das liest sich wie eine Wertung.
        still = _seat(game, "Ida")
        still.eliminated, still.eliminated_round = True, 3

        assert game.ghost_league() == []

    def test_a_tie_favours_the_longer_ghost(self, game: GameState):
        frueh = _seat(game, "Tom")
        frueh.eliminated, frueh.eliminated_round = True, 2
        frueh.ghost_score, frueh.ghost_rounds = 200, 5
        spaet = _seat(game, "Kim")
        spaet.eliminated, spaet.eliminated_round = True, 6
        spaet.ghost_score, spaet.ghost_rounds = 200, 2

        # Gleiche Summe: die frueher ausgeschiedene steht oben. Der Award geht
        # trotzdem an Kim (Schnitt) — Tabelle und Karte beantworten bewusst
        # zwei verschiedene Fragen.
        assert [g["name"] for g in game.ghost_league()] == ["Tom", "Kim"]

    def test_a_new_game_clears_the_ghost_bilanz(self, game: GameState):
        tom = _seat(game, "Tom")
        tom.eliminated = True
        tom.ghost_score, tom.ghost_rounds = 340, 5
        tom.reset_for_new_game()
        assert tom.ghost_score == 0
        assert tom.ghost_rounds == 0
