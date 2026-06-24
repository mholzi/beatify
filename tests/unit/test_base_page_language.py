"""Tests for the server-side ``<html lang>`` resolution helpers (#1527).

PR #1527 rewrites the static ``<html lang="en">`` to the active locale before
the page is served, so Android Chrome's auto-translate (which runs against the
*initial* HTML, before the JS ``setLanguage()`` fires) no longer re-translates
the already-correct UI. These tests pin the resolution priority:

1. active game's language → 2. ``hass.config.language`` → 3. ``"en"``.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server.base import (
    _apply_html_lang,
    _resolve_page_language,
)


def _make_hass(*, game_language=..., config_language=...):
    """Build a minimal hass stub.

    Pass ``...`` (the default) to omit a layer entirely: no ``game`` key when
    ``game_language`` is omitted, and no ``config`` attribute when
    ``config_language`` is omitted — mirroring the bare-hass case the helper
    guards against.
    """
    data: dict = {DOMAIN: {}}
    if game_language is not ...:
        data[DOMAIN]["game"] = SimpleNamespace(language=game_language)
    hass = SimpleNamespace(data=data)
    if config_language is not ...:
        hass.config = SimpleNamespace(language=config_language)
    return hass


class TestResolvePageLanguage:
    """#1527: resolution priority active-game → hass.config → 'en'."""

    def test_active_game_language_wins(self):
        """An active game's language beats hass.config."""
        hass = _make_hass(game_language="de", config_language="fr")

        assert _resolve_page_language(hass) == "de"

    def test_falls_back_to_hass_config_without_game(self):
        """No active game → use Home Assistant's configured UI language."""
        hass = _make_hass(config_language="fr")

        assert _resolve_page_language(hass) == "fr"

    def test_falls_back_to_config_when_game_language_falsy(self):
        """A game with no usable language must not shadow hass.config."""
        hass = _make_hass(game_language=None, config_language="nl")

        assert _resolve_page_language(hass) == "nl"

    def test_defaults_to_en_without_game_or_config(self):
        """Nothing to resolve → last-resort 'en'."""
        hass = _make_hass()

        assert _resolve_page_language(hass) == "en"

    def test_defaults_to_en_when_config_attr_missing(self):
        """A bare hass without a config attribute degrades to 'en', not raises."""
        hass = _make_hass()
        # No `config` attribute at all (bare test/stub hass).
        assert not hasattr(hass, "config")

        assert _resolve_page_language(hass) == "en"


class TestApplyHtmlLang:
    """#1527: rewrite the literal ``<html lang="en">`` to the active locale."""

    def test_rewrites_lang_attribute(self):
        """The shipped literal is replaced with the resolved locale."""
        hass = _make_hass(game_language="de")
        html = '<!doctype html><html lang="en"><head></head></html>'

        assert _apply_html_lang(html, hass) == (
            '<!doctype html><html lang="de"><head></head></html>'
        )

    def test_noop_when_literal_absent(self):
        """A template without the exact literal is left untouched."""
        hass = _make_hass(game_language="de")
        html = "<html lang='en'>"  # single quotes — not the shipped literal

        assert _apply_html_lang(html, hass) == html

    def test_only_first_occurrence_rewritten(self):
        """Replace count is 1 — only the document's opening tag is touched."""
        hass = _make_hass(config_language="fr")
        html = '<html lang="en"> ... <html lang="en">'

        assert _apply_html_lang(html, hass) == ('<html lang="fr"> ... <html lang="en">')
