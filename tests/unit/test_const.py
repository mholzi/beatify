"""Tests for Beatify constants."""


def test_domain_constant():
    """Test DOMAIN constant is correctly set."""
    from custom_components.beatify.const import DOMAIN

    assert DOMAIN == "beatify"


def test_game_configuration_constants():
    """Test game configuration constants have expected values."""
    from custom_components.beatify.const import (
        DEFAULT_ROUND_DURATION,
        MAX_NAME_LENGTH,
        MAX_PLAYERS,
        MIN_NAME_LENGTH,
        MIN_PLAYERS,
        RECONNECT_TIMEOUT,
    )

    assert MAX_PLAYERS == 20
    assert MIN_PLAYERS == 2
    assert RECONNECT_TIMEOUT == 60
    assert DEFAULT_ROUND_DURATION == 30
    assert MAX_NAME_LENGTH == 20
    assert MIN_NAME_LENGTH == 1


def test_error_code_constants():
    """Test error code constants are correctly defined."""
    from custom_components.beatify.const import (
        ERR_GAME_ALREADY_STARTED,
        ERR_GAME_NOT_STARTED,
        ERR_INVALID_ACTION,
        ERR_MA_UNAVAILABLE,
        ERR_NAME_INVALID,
        ERR_NAME_TAKEN,
        ERR_NOT_ADMIN,
        ERR_ROUND_EXPIRED,
    )

    assert ERR_NAME_TAKEN == "NAME_TAKEN"
    assert ERR_NAME_INVALID == "NAME_INVALID"
    assert ERR_GAME_NOT_STARTED == "GAME_NOT_STARTED"
    assert ERR_GAME_ALREADY_STARTED == "GAME_ALREADY_STARTED"
    assert ERR_NOT_ADMIN == "NOT_ADMIN"
    assert ERR_ROUND_EXPIRED == "ROUND_EXPIRED"
    assert ERR_MA_UNAVAILABLE == "MA_UNAVAILABLE"
    assert ERR_INVALID_ACTION == "INVALID_ACTION"


def test_logger_is_configured():
    """Test logger is properly configured."""
    from custom_components.beatify.const import _LOGGER

    assert _LOGGER is not None
    assert _LOGGER.name == "custom_components.beatify.const"
