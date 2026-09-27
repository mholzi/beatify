"""#3030: GameState and its mixins are type-checked, and the contract costs nothing at runtime.

The fourteen ``state_*.py`` mixins used to declare none of the attributes and
sibling methods they reach through ``self``, so mypy could not check them and
``[tool.mypy] files`` had to leave all of them out (#1275). They now inherit
``GameStateBase`` from ``game/state_contract.py``, which is the declared
contract under ``TYPE_CHECKING`` and plain ``object`` at runtime.

These tests pin both halves: every GameState module stays in the mypy gate, and
the contract adds no class to the MRO and no attribute to the mixins.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from custom_components.beatify.game import state_contract
from custom_components.beatify.game.state import GameState

ROOT = Path(__file__).parents[2]
GAME = ROOT / "custom_components" / "beatify" / "game"


def _mypy_files() -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(config["tool"]["mypy"]["files"])


class TestMypyGate:
    def test_state_and_every_mixin_module_is_gated(self):
        gated = _mypy_files()
        modules = sorted(GAME.glob("state*.py"))
        assert len(modules) >= 16, "expected state.py, the contract and 14 mixins"
        missing = [
            p.name for p in modules if p.relative_to(ROOT).as_posix() not in gated
        ]
        assert not missing, f"not in [tool.mypy] files: {missing}"


class TestContractIsTypeCheckingOnly:
    def test_base_is_object_at_runtime(self):
        assert state_contract.GameStateBase is object
        assert not hasattr(state_contract, "GameStateContract")

    def test_mixins_still_derive_from_object_only(self):
        mixins = GameState.__bases__
        assert len(mixins) == 14
        for mixin in mixins:
            assert mixin.__bases__ == (object,), mixin.__name__

    def test_mro_is_gamestate_its_mixins_and_object(self):
        assert GameState.__mro__ == (GameState, *GameState.__bases__, object)

    def test_contract_adds_no_class_attributes(self):
        """Annotations only: nothing that could shadow instance state."""
        for mixin in GameState.__bases__:
            for name in ("phase", "players", "_round_manager", "_score_lock"):
                assert name not in vars(mixin) or isinstance(
                    vars(mixin)[name], property
                ), f"{mixin.__name__}.{name}"
