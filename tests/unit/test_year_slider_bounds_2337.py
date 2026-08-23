"""Die Grenzen des Jahres-Schiebers muessen die Playlist enthalten (#2337).

Das Markup lieferte ``min="1950" max="2025"`` aus, waehrend **46** Songs im
Katalog ``year: 2026`` tragen — `world-cup-anthems` und `wiesn-party-hits`,
also ausgerechnet die beiden Playlists mit Saison. Fuer diese Runden war die
richtige Antwort **nicht eingebbar**: der Regler endete davor. In Sudden Death
entscheidet das ein Ausscheiden.

Das Schema hatte diese Lehre laengst gezogen — ``_max_year`` ist seit #706
dynamisch, *damit* eine feste Zahl keine neueren Songs mehr stillschweigend
ablehnt. Die Oberflaeche behielt ihre feste Zahl.

**Der Bereich wird geweitet, nie verengt.** Gaebe der Server die exakte Spanne
der Playlist heraus, wuesste der Raum vor dem ersten Ton, dass die Antwort
zwischen 1980 und 1995 liegt — eine groessere Aenderung am Spiel als der
Fehler, um den es geht.
"""

from __future__ import annotations

from datetime import datetime, timezone

from custom_components.beatify.game.playlist import PlaylistManager
from custom_components.beatify.game.serializers import (
    _SLIDER_DEFAULT_MIN_YEAR,
    GameStateSerializer,
)


def _songs(*years: int) -> list[dict]:
    return [
        {"year": y, "uri": f"spotify:track:{i:022d}", "artist": "A", "title": "T"}
        for i, y in enumerate(years)
    ]


class _FakeState:
    """Nur das Feld, das ``_year_range`` anfasst."""

    def __init__(self, manager) -> None:
        self._playlist_manager = manager


class _FakeManager:
    def __init__(self, span):
        self._span = span

    def get_year_span(self):
        return self._span


def _this_year() -> int:
    return datetime.now(timezone.utc).year


class TestYearSpan:
    def test_span_over_real_songs(self):
        pm = PlaylistManager.__new__(PlaylistManager)
        pm._songs = _songs(1984, 2026, 1999)
        assert pm.get_year_span() == (1984, 2026)

    def test_songs_without_a_usable_year_are_ignored(self):
        pm = PlaylistManager.__new__(PlaylistManager)
        pm._songs = _songs(1984) + [{"year": None}, {"year": "1990"}, {}]
        assert pm.get_year_span() == (1984, 1984)

    def test_no_usable_year_returns_none(self):
        # Nicht (0, 0) und nicht (heute, heute): wer nichts weiss, soll dem
        # Aufrufer seine eigenen Vorgaben lassen.
        pm = PlaylistManager.__new__(PlaylistManager)
        pm._songs = [{"year": None}, {}]
        assert pm.get_year_span() is None

    def test_absurd_years_are_ignored(self):
        # Das Schema laesst MIN_YEAR..(Jahr+1) zu; alles davor oder danach ist
        # ein Datenfehler und darf den Regler nicht auf 3000 aufziehen.
        pm = PlaylistManager.__new__(PlaylistManager)
        pm._songs = _songs(1984, 1300, 3000)
        assert pm.get_year_span() == (1984, 1984)


class TestSliderBounds:
    def test_the_2026_case_the_issue_was_opened_for(self):
        r = GameStateSerializer._year_range(_FakeState(_FakeManager((1975, 2026))))
        assert r["max"] >= 2026, "Songs von 2026 muessen eingebbar sein"
        assert r["min"] == _SLIDER_DEFAULT_MIN_YEAR

    def test_a_narrow_playlist_does_not_narrow_the_slider(self):
        # Der Kern der Entscheidung: die Spanne 1980-1995 wuerde die Antwort
        # verraten, bevor ein Ton gespielt hat.
        r = GameStateSerializer._year_range(_FakeState(_FakeManager((1980, 1995))))
        assert r["min"] == _SLIDER_DEFAULT_MIN_YEAR
        assert r["max"] == _this_year()

    def test_an_old_song_widens_the_lower_bound(self):
        r = GameStateSerializer._year_range(_FakeState(_FakeManager((1927, 1960))))
        assert r["min"] == 1927

    def test_without_a_playlist_the_defaults_hold(self):
        r = GameStateSerializer._year_range(_FakeState(None))
        assert r == {"min": _SLIDER_DEFAULT_MIN_YEAR, "max": _this_year()}

    def test_a_playlist_without_years_leaves_the_defaults(self):
        r = GameStateSerializer._year_range(_FakeState(_FakeManager(None)))
        assert r == {"min": _SLIDER_DEFAULT_MIN_YEAR, "max": _this_year()}

    def test_the_upper_default_follows_the_clock(self):
        # Der eigentliche Schutz gegen das Wiederauftreten: eine feste Zahl
        # verfaellt jeden Januar, und zwar unbemerkt.
        r = GameStateSerializer._year_range(_FakeState(None))
        assert r["max"] == _this_year()
        assert r["max"] > 2025
