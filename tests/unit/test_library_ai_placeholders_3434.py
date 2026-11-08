"""#3434: Crate Digger AI modal placeholders must be translated, not hardcoded."""

import json
import re
from pathlib import Path

WWW = Path(__file__).resolve().parents[2] / "custom_components/beatify/www"
SRC = (WWW / "js/admin/sections/library-ai.js").read_text(encoding="utf-8")
LANGS = ["de", "en", "es", "fr", "it", "nl"]


def test_text_inputs_bind_placeholder_keys():
    for key in ("namePlaceholder", "themePlaceholder"):
        assert f'data-i18n-placeholder="admin.libraryAi.{key}"' in SRC


def test_placeholder_keys_exist_in_every_locale():
    for lang in LANGS:
        data = json.loads((WWW / f"i18n/{lang}.json").read_text(encoding="utf-8"))
        block = data["admin"]["libraryAi"]
        for key in ("namePlaceholder", "themePlaceholder"):
            assert block.get(key), f"{lang}: missing {key}"


def test_every_bound_key_is_defined():
    for key in re.findall(r'data-i18n-placeholder="admin\.libraryAi\.(\w+)"', SRC):
        assert (
            key in json.loads((WWW / "i18n/en.json").read_text())["admin"]["libraryAi"]
        )
