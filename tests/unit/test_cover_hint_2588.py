"""#2588: the cover hint appears only where the fun fact really contradicts.

A cover's fun fact often names the year of the ORIGINAL — right next to the
answer, with the report button beside it. That is how #2587 came about: "Randy
Newman wrote the song in 1972" sat next to the correct answer 1986, and a
player reported an error that was none.

Design variant D of four: show the hint **only on a real contradiction**, not
on all 740 cover entries, and name the number it is about.

Measured across all 66 playlists: 1110 of 8403 entries name a differing year in
their fun fact, but only 740 carry `alt_artists`. The cover condition is what
separates a hint from noise — Jamala's "1944" is about a deportation, not a
release.
"""

from __future__ import annotations

import datetime

from custom_components.beatify.game.serializers import GameStateSerializer as S


def _song(**kw):
    basis = {
        "title": "You Can Leave Your Hat On",
        "artist": "Joe Cocker",
        "year": 1986,
        "alt_artists": ["Randy Newman"],
        "fun_fact": "Randy Newman wrote and recorded it in 1972.",
    }
    basis.update(kw)
    return basis


class TestCoverOriginalYear:
    def test_the_real_case_from_2587(self):
        assert S._cover_original_year(_song()) == 1972

    def test_no_hint_without_alt_artists(self):
        """A year in an original's fun fact is usually a historical reference,
        not a contradiction — Jamala's '1944' is about a deportation."""
        jamala = {
            "title": "1944",
            "artist": "Jamala",
            "year": 2016,
            "fun_fact": "The song is about the 1944 deportation of the Crimean Tatars.",
        }
        assert S._cover_original_year(jamala) is None

    def test_no_hint_when_the_fun_fact_agrees(self):
        s = _song(fun_fact="Cocker recorded it in 1986 for the film.")
        assert S._cover_original_year(s) is None

    def test_no_hint_without_a_fun_fact(self):
        assert S._cover_original_year(_song(fun_fact="")) is None

    def test_a_translated_fun_fact_counts_too(self):
        """The server does not know which language the player reads, and a
        translation can carry the number where the original paraphrases it."""
        s = _song(fun_fact="Newman's version came first.")
        s["fun_fact_de"] = "Randy Newman nahm den Song 1972 auf."
        assert S._cover_original_year(s) == 1972

    def test_the_earliest_differing_year_wins(self):
        """A cover is younger than its original, so the smaller number is the
        one that creates the contradiction."""
        s = _song(fun_fact="Written 1972, re-recorded 1980, covered again 1991.")
        assert S._cover_original_year(s) == 1972

    def test_a_year_in_the_future_is_ignored(self):
        heute = datetime.date.today().year
        s = _song(fun_fact=f"A remaster is planned for {heute + 3}.")
        assert S._cover_original_year(s) is None

    def test_a_missing_year_field_yields_nothing(self):
        assert S._cover_original_year(_song(year=None)) is None
