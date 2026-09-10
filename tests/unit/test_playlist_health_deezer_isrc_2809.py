"""#2809: the Deezer ISRC check has to acquit, not convict.

#2787 replaced a display-title comparison with an ISRC lookup, because Deezer
prefixes compilation titles with the album name and the title match misread
that as a wrong track. The lookup asked `track/isrc:<x>` and compared the id it
returned with the stored one.

Deezer's catalogue holds the same recording many times — album, single,
compilation, regional release — each with its own track id and the **same**
ISRC. Which one that endpoint returns is not ours to choose. The first run
after the change flagged 11 of 11 tracks on `community/polish-rock.json`, and
every stored URI carried exactly the ISRC its entry claimed.

So the question is not "is our id the one Deezer returns for this ISRC" but "is
our id a recording with this ISRC" — and `/track/<id>` answers it directly.

The asymmetry below is the point: an ISRC match is proof of identity, an ISRC
mismatch is not proof of anything. A different mastering legitimately carries a
different ISRC, and the entry's ISRC may have come from another provider.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude/skills/playlist-health-check/scripts/validate_uris.py"
)


@pytest.fixture(scope="module")
def validator():
    spec = importlib.util.spec_from_file_location("validate_uris_2809", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _deezer(monkeypatch, validator, track: dict, by_isrc: dict | None = None):
    """Answer /track/<id> with `track` and /track/isrc:<x> with `by_isrc`."""
    calls: list[str] = []

    def fake(url, **kwargs):
        calls.append(url)
        if "isrc:" in url:
            return (by_isrc or {"error": {"message": "not found"}}), 200, False
        return track, 200, False

    monkeypatch.setattr(validator, "http_json", fake)
    return calls


class TestAnIsrcMatchIsProof:
    def test_the_stored_track_carrying_the_isrc_is_accepted(
        self, validator, monkeypatch
    ):
        """The exact shape of all 11 false findings on polish-rock."""
        calls = _deezer(
            monkeypatch,
            validator,
            {
                "id": 458821712,
                "isrc": "PLB821800003",
                "title": "Nie Raj",
                "artist": {"name": "Lao Che"},
            },
            # The lookup would hand back a different copy of the same recording.
            by_isrc={"id": 449479872, "isrc": "PLB821800003"},
        )

        got = validator.check_deezer(
            "458821712", "Nie raj", "Lao Che", isrc="PLB821800003"
        )

        assert got["status"] == "ok", got
        assert not any("isrc:" in c for c in calls), (
            "the reverse lookup was asked anyway — that is the request whose "
            "answer caused #2809"
        )

    def test_case_and_spacing_do_not_matter(self, validator, monkeypatch):
        _deezer(
            monkeypatch,
            validator,
            {"id": 1, "isrc": " plb821800003 ", "title": "x", "artist": {"name": "y"}},
        )
        got = validator.check_deezer("1", "x", "y", isrc="PLB821800003")
        assert got["status"] == "ok"


class TestAnIsrcMismatchIsNotProof:
    def test_a_different_isrc_falls_through_to_the_title(self, validator, monkeypatch):
        """A remaster carries its own ISRC and is still the right song."""
        _deezer(
            monkeypatch,
            validator,
            {
                "id": 2,
                "isrc": "GBAAA0000001",
                "title": "Naiwne pytania",
                "artist": {"name": "Dżem"},
            },
        )

        got = validator.check_deezer("2", "Naiwne pytania", "Dżem", isrc="PLB010300013")

        assert got["status"] == "ok", (
            "a differing ISRC convicted a track whose title and artist match — "
            "the ISRC may only acquit"
        )

    def test_a_genuinely_wrong_track_is_still_reported(self, validator, monkeypatch):
        """The check still has to be able to fail."""
        _deezer(
            monkeypatch,
            validator,
            {
                "id": 3,
                "isrc": "GBAAA0000002",
                "title": "Something Else Entirely",
                "artist": {"name": "Another Band"},
            },
        )

        got = validator.check_deezer("3", "Nie raj", "Lao Che", isrc="PLB821800003")

        assert got["status"] == "wrong_track", got

    def test_a_track_without_an_isrc_still_gets_judged(self, validator, monkeypatch):
        """Deezer does not always return one; the title decides then."""
        _deezer(
            monkeypatch,
            validator,
            {"id": 4, "title": "Nie Raj", "artist": {"name": "Lao Che"}},
        )
        got = validator.check_deezer("4", "Nie raj", "Lao Che", isrc="PLB821800003")
        assert got["status"] == "ok"
