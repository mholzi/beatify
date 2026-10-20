"""#3235 - a speaker that cannot play Amazon Music gets Echo advice.

``errors.PROVIDER_NOT_SUPPORTED`` tells the host to switch to a Music Assistant
speaker. Amazon Music is not on Music Assistant at all, it only plays on an
Amazon Echo, so its refusal carries its own ``message_key`` and the
machine-readable ``provider_id``. Every other provider keeps the generic text.
"""

from __future__ import annotations

import json

import pytest

from custom_components.beatify.server.game_views import _check_speaker_platform


def _body(platform: str, provider: str) -> dict:
    resp = _check_speaker_platform(platform, provider, speaker_name="Küche")
    assert resp is not None
    assert resp.status == 400
    return json.loads(resp.body)


def test_amazon_music_on_music_assistant_gets_the_echo_key():
    body = _body("music_assistant", "amazon_music")
    assert body["code"] == "PROVIDER_NOT_SUPPORTED"
    assert body["message_key"] == "PROVIDER_NOT_SUPPORTED_AMAZON"
    assert body["provider_id"] == "amazon_music"
    assert body["speaker"] == "Küche"
    assert body["provider"] == "Amazon Music"
    # The English server text is unchanged and already pointed at an Echo.
    assert "Amazon Echo" in body["message"]


@pytest.mark.parametrize("provider", ["youtube_music", "tidal", "deezer"])
def test_other_providers_keep_the_generic_text(provider):
    body = _body("alexa_media", provider)
    assert body["code"] == "PROVIDER_NOT_SUPPORTED"
    assert "message_key" not in body
    assert body["provider_id"] == provider


def test_amazon_music_on_an_echo_passes():
    assert (
        _check_speaker_platform("alexa_media", "amazon_music", speaker_name="Echo")
        is None
    )
