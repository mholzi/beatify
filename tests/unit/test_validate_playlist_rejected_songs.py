"""Tests for the structured ``rejected_songs`` out-param of ``validate_playlist``
and the ``summarize_rejected_songs`` renderer (#1576).

The host needs to see *which* tracks dropped and *why* when loading a flawed
playlist, not just the flat positional ``errors`` strings. These tests pin:

* the structured record shape (``index``/``title``/``artist``/``reasons``),
* the back-compat guarantee that passing ``rejected_songs`` never changes the
  ``errors`` list (byte-for-byte identical to the legacy call), and
* the host-readable one-liner produced by ``summarize_rejected_songs``.
"""

from __future__ import annotations

from typing import Any

from custom_components.beatify.game.playlist import (
    summarize_rejected_songs,
    validate_playlist,
)

VALID_SONG: dict[str, Any] = {
    "title": "Bohemian Rhapsody",
    "artist": "Queen",
    "year": 1975,
    "uri": "spotify:track:3z8h0TU7ReDPLIbEnYhWZb",
}


def _playlist(*songs: dict[str, Any]) -> dict[str, Any]:
    return {"name": "Test", "songs": list(songs)}


# ---------------------------------------------------------------------------
# rejected_songs structure
# ---------------------------------------------------------------------------


class TestRejectedSongsStructure:
    def test_valid_playlist_leaves_rejected_songs_empty(self):
        rejected: list[dict[str, Any]] = []
        is_valid, errors = validate_playlist(
            _playlist(VALID_SONG), rejected_songs=rejected
        )
        assert is_valid is True
        assert errors == []
        assert rejected == []

    def test_one_record_per_flawed_song_with_index_and_reasons(self):
        bad = {"title": "X", "artist": "Y", "year": 1500}  # out of range + no URI
        rejected: list[dict[str, Any]] = []
        is_valid, _ = validate_playlist(
            _playlist(VALID_SONG, bad), rejected_songs=rejected
        )
        assert is_valid is False
        assert len(rejected) == 1
        rec = rejected[0]
        # 1-based index: the bad song is the 2nd entry.
        assert rec["index"] == 2
        assert rec["title"] == "X"
        assert rec["artist"] == "Y"
        assert "year 1500 out of range" in rec["reasons"]
        assert "no valid URI" in rec["reasons"]

    def test_missing_title_and_artist_are_none(self):
        bad = {"year": 1975, "uri": "spotify:track:3z8h0TU7ReDPLIbEnYhWZb"}
        rejected: list[dict[str, Any]] = []
        validate_playlist(_playlist(bad), rejected_songs=rejected)
        assert len(rejected) == 1
        assert rejected[0]["title"] is None
        assert rejected[0]["artist"] is None
        assert "missing or empty 'title'" in rejected[0]["reasons"]
        assert "missing or empty 'artist'" in rejected[0]["reasons"]

    def test_non_object_song_records_not_a_valid_object(self):
        rejected: list[dict[str, Any]] = []
        validate_playlist(_playlist(VALID_SONG, "oops"), rejected_songs=rejected)
        assert len(rejected) == 1
        rec = rejected[0]
        assert rec["index"] == 2
        assert rec["title"] is None
        assert rec["artist"] is None
        assert rec["reasons"] == ["not a valid object"]

    def test_reasons_omit_the_song_n_prefix(self):
        bad = {"title": "X", "artist": "Y", "year": 1975}  # no URI only
        rejected: list[dict[str, Any]] = []
        validate_playlist(_playlist(bad), rejected_songs=rejected)
        assert rejected[0]["reasons"] == ["no valid URI"]


# ---------------------------------------------------------------------------
# errors back-compat — the out-param must not change the flat errors list
# ---------------------------------------------------------------------------


class TestErrorsBackCompat:
    def test_errors_identical_with_and_without_out_param(self):
        bad = {"title": "X", "year": 1500}  # missing artist + out of range + no URI
        doc = _playlist(VALID_SONG, bad, "oops")

        _, errors_legacy = validate_playlist(doc)
        rejected: list[dict[str, Any]] = []
        _, errors_new = validate_playlist(doc, rejected_songs=rejected)

        # Byte-for-byte identical: passing the out-param only makes the existing
        # rejections observable, it never alters which strings are produced.
        assert errors_new == errors_legacy
        # And the structured view captured the same rejected tracks.
        assert {r["index"] for r in rejected} == {2, 3}

    def test_validity_verdict_unchanged_by_out_param(self):
        doc = _playlist(VALID_SONG)
        assert validate_playlist(doc)[0] == (
            validate_playlist(doc, rejected_songs=[])[0]
        )


# ---------------------------------------------------------------------------
# summarize_rejected_songs renderer
# ---------------------------------------------------------------------------


class TestSummarizeRejectedSongs:
    def test_empty_input_renders_empty_string(self):
        assert summarize_rejected_songs([]) == ""

    def test_title_artist_label_with_joined_reasons(self):
        rejected = [
            {
                "index": 1,
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "reasons": ["year 1500 out of range", "no valid URI"],
            }
        ]
        out = summarize_rejected_songs(rejected)
        assert out == (
            "Bohemian Rhapsody — Queen "
            "(year 1500 out of range, no valid URI)"
        )

    def test_falls_back_to_song_index_label_when_no_title(self):
        rejected = [
            {"index": 4, "title": None, "artist": None, "reasons": ["no valid URI"]}
        ]
        assert summarize_rejected_songs(rejected) == "Song #4 (no valid URI)"

    def test_truncates_with_plus_n_more(self):
        rejected = [
            {"index": i, "title": f"T{i}", "artist": "A", "reasons": ["no valid URI"]}
            for i in range(1, 9)  # 8 rejected, default limit 5
        ]
        out = summarize_rejected_songs(rejected)
        assert out.endswith("+3 more")
        # Only the first `limit` labelled entries appear before the suffix.
        assert out.count(" — A (") == 5
