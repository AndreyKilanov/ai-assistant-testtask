"""Границы слоёв проверяет import-linter по контрактам из pyproject.toml."""

from importlinter.cli import lint_imports


def test_layer_contracts_are_kept() -> None:
    assert lint_imports() == 0
