"""A view's rate limit must use the name the mixin reads (#2628).

``RateLimitMixin._check_rate_limit`` reads exactly one attribute for the
count, ``RATE_LIMIT_REQUESTS``, defaulting to 5. Two library views set
``RATE_LIMIT_MAX_REQUESTS`` instead — 30 and 15 — so nothing read them and
both endpoints ran at 5 requests per minute, a third and a sixth of the
intended limit.

What made it invisible is worth keeping in mind: the *second* attribute on
both views, ``RATE_LIMIT_WINDOW``, carries the correct name and did take
effect. A half-correct pair reads as a configured limit at a glance.

The guard below is deliberately not a check of two numbers. It walks every
view class in the package and fails on any ``RATE_LIMIT_*`` attribute the
mixin does not declare, so the next near-miss name fails here rather than
silently throttling an endpoint.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from custom_components.beatify.server.base import RateLimitMixin

KNOWN = {n for n in vars(RateLimitMixin) if n.startswith("RATE_LIMIT")}


def _view_classes():
    import custom_components.beatify.server as server_pkg

    for mod in pkgutil.iter_modules(server_pkg.__path__):
        module = importlib.import_module(f"custom_components.beatify.server.{mod.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is RateLimitMixin or not issubclass(obj, RateLimitMixin):
                continue
            if obj.__module__ != module.__name__:
                continue  # imported, counted where it is defined
            yield obj


class TestAttributeNames:
    def test_the_mixin_still_reads_the_name_we_assume(self):
        src = inspect.getsource(RateLimitMixin._check_rate_limit)
        assert "self.RATE_LIMIT_REQUESTS" in src
        assert "RATE_LIMIT_MAX_REQUESTS" not in src

    def test_no_view_sets_a_rate_limit_attribute_nobody_reads(self):
        offenders = [
            (cls.__module__, cls.__name__, name)
            for cls in _view_classes()
            for name in vars(cls)
            if name.startswith("RATE_LIMIT") and name not in KNOWN
        ]
        assert not offenders, (
            "these views set a RATE_LIMIT attribute the mixin never reads, so "
            f"they silently run at the default of {RateLimitMixin.RATE_LIMIT_REQUESTS}"
            f"/window: {offenders}"
        )

    @pytest.mark.parametrize(
        ("view_name", "expected"),
        [("LibraryPlaylistResolveView", 30), ("LibraryPlaylistGenerateView", 15)],
    )
    def test_the_two_library_views_carry_their_intended_limit(
        self, view_name, expected
    ):
        from custom_components.beatify.server import library_views

        assert getattr(library_views, view_name).RATE_LIMIT_REQUESTS == expected
