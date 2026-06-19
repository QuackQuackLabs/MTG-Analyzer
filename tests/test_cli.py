"""Offline CLI smoke tests (save / list / diff) — no network, no card DB."""

from pathlib import Path

import pytest

from mtg_analyzer import config
from mtg_analyzer.cli import main

DECK_A = "// COMMANDER\n1 Sol Ring (LTC) 284\n\n1 Llanowar Elves (M19) 314\n1 Counterspell (MH2) 267\n"
DECK_B = "// COMMANDER\n1 Sol Ring (LTC) 284\n\n1 Llanowar Elves (M19) 314\n1 Cultivate (M21) 177\n"


def test_deck_save_list_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # saved decks land under tmp
    (tmp_path / "a.txt").write_text(DECK_A)
    (tmp_path / "b.txt").write_text(DECK_B)

    assert main(["deck", "save", "deck-a", str(tmp_path / "a.txt")]) == 0
    assert main(["deck", "save", "deck-b", str(tmp_path / "b.txt")]) == 0

    assert main(["deck", "list"]) == 0
    listing = capsys.readouterr().out
    assert "deck-a" in listing and "deck-b" in listing

    # diff resolves saved names; b adds Cultivate and drops Counterspell vs a
    assert main(["deck", "diff", "deck-a", "deck-b"]) == 0
    diff = capsys.readouterr().out
    assert "Cultivate" in diff  # added
    assert "Counterspell" in diff  # removed


def test_deck_remove_missing_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert main(["deck", "remove", "does-not-exist"]) == 1


def test_diff_identical_decks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "a.txt").write_text(DECK_A)
    assert main(["deck", "diff", str(tmp_path / "a.txt"), str(tmp_path / "a.txt")]) == 0
    assert "identical" in capsys.readouterr().out
