"""#2935 — the library "save as playlist" endpoint crashed on its own first line.

``LibraryPlaylistGenerateView.post`` unpacked three values from
``_parse_library_config``, which returns five. Every call raised
``ValueError: too many values to unpack (expected 3)`` before the endpoint did
anything, and the admin library panel calls it whenever a host presses "save as
playlist".

The two values it never bound are ``popularity_percent`` and ``genres`` — the
filters the panel sends. Widening the unpack alone would have replaced a visible
500 with a silently ignored setting, so the tests below assert both halves: the
call succeeds, *and* the filters arrive at the generator.

Nothing caught this because ``_parse_library_config`` is imported inside the
function to dodge the import cycle (#2930), so growing it from three return
values to five never surfaced here.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.server.library_views import (
    LibraryPlaylistGenerateView,
)


def _request(body: dict) -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.remote = "10.0.0.1"
    return request


@pytest.fixture
def view():
    return LibraryPlaylistGenerateView(MagicMock())


@patch(
    "custom_components.beatify.server.library_views.is_authorized_http",
    return_value=True,
)
class TestGenerateEndpointParsesItsBody:
    async def test_a_plain_request_does_not_raise(self, _auth, view):
        """The regression itself: this used to die on the unpack."""
        with patch(
            "custom_components.beatify.library.async_generate_library_playlist",
            AsyncMock(return_value=None),
        ):
            resp = await view.post(_request({"size": 30}))

        # None from the generator is the "pool not scanned" branch — a 400 with
        # a code, which means the body was parsed and the call was made.
        assert resp.status == 400
        assert json.loads(resp.body)["code"] == "LIBRARY_POOL_MISSING"

    async def test_popularity_and_genres_reach_the_generator(self, _auth, view):
        """The half that a wider unpack alone would have left broken."""
        generate = AsyncMock(return_value=None)
        with patch(
            "custom_components.beatify.library.async_generate_library_playlist",
            generate,
        ):
            await view.post(
                _request(
                    {
                        "size": 40,
                        "difficulty": 70,
                        "popularity_percent": 25,
                        "genres": ["rock", "pop"],
                    }
                )
            )

        kwargs = generate.await_args.kwargs
        assert kwargs["size"] == 40
        assert kwargs["difficulty_slider"] == 70
        assert kwargs["popularity_percent"] == 25
        assert kwargs["genres"] == ["rock", "pop"]

    async def test_absent_filters_are_passed_as_none(self, _auth, view):
        """An empty genre list must not reach the generator as ``[]``.

        ``genres or None`` is deliberate: the generator treats ``None`` as "no
        filter" and would read an empty list as "match nothing".
        """
        generate = AsyncMock(return_value=None)
        with patch(
            "custom_components.beatify.library.async_generate_library_playlist",
            generate,
        ):
            await view.post(_request({"size": 30}))

        kwargs = generate.await_args.kwargs
        assert kwargs["popularity_percent"] is None
        assert kwargs["genres"] is None
