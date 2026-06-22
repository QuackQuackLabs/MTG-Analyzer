"""Tests for the real-game log (Phase 9C-1): model validation + append-only JSONL round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_analyzer.cli import _collect_game_form, _select_indices
from mtg_analyzer.data.match_log import MatchLog
from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.models.match_log import LoggedGame


def _prof(name: str) -> BattleProfile:
    return BattleProfile(
        name=name, archetype="midrange", clock_mean=7.0, clock_sd=1.4, interaction=6,
        sweepers=1, card_advantage=8, has_combo=False, tutors=0, threat_level=5.0,
    )


def _game(**kw: object) -> LoggedGame:
    pod = ["henzie", "sauron", "galadriel"]
    base: dict[str, object] = {
        "date": "2026-06-22", "pod": pod, "winner": "sauron", "died_first": "galadriel",
        "end_turn": 11, "profiles": {p: _prof(p) for p in pod},
    }
    base.update(kw)
    return LoggedGame.model_validate(base)


def test_winner_must_be_in_pod() -> None:
    with pytest.raises(ValueError, match="winner"):
        _game(winner="frodo-and-sam")


def test_optional_fields_validated_against_pod() -> None:
    with pytest.raises(ValueError, match="died_first"):
        _game(died_first="not-in-pod")
    with pytest.raises(ValueError, match="win_method"):
        _game(win_method="ramp")  # not a recognized method


def test_pod_size_and_profile_coverage() -> None:
    with pytest.raises(ValueError, match="2–4 decks"):
        _game(pod=["solo"], winner="solo", died_first=None, profiles={"solo": _prof("solo")})
    with pytest.raises(ValueError, match="missing profile"):
        _game(profiles={"henzie": _prof("henzie")})  # sauron/galadriel snapshots absent


def test_append_and_load_roundtrip(tmp_path: Path) -> None:
    log = MatchLog(tmp_path / "match_log.jsonl")
    assert log.load().games == []  # empty before anything is written
    log.append(_game())
    log.append(_game(date="2026-06-23", winner="henzie", died_first="galadriel"))
    res = log.load()
    assert len(res.games) == 2 and not res.errors
    assert res.games[1].winner == "henzie"
    # The as-played profile snapshot survives the round-trip (drift insurance).
    assert res.games[0].profiles["sauron"].archetype == "midrange"


def test_malformed_lines_are_surfaced_not_dropped(tmp_path: Path) -> None:
    log = MatchLog(tmp_path / "match_log.jsonl")
    log.append(_game())
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not valid json\n")
        fh.write('{"date": "2026-06-24", "pod": ["a", "b"]}\n')  # valid json, invalid game
    res = log.load()
    assert len(res.games) == 1  # the one good row
    assert len(res.errors) == 2 and "line 2" in res.errors[0] and "line 3" in res.errors[1]


def test_select_indices_parses_and_validates() -> None:
    assert _select_indices("1 3 4", 6) == [0, 2, 3]
    assert _select_indices("2,4", 4) == [1, 3]  # comma-separated
    with pytest.raises(ValueError, match="out of range"):
        _select_indices("5", 4)
    with pytest.raises(ValueError, match="repeated"):
        _select_indices("1 1", 4)
    with pytest.raises(ValueError, match="isn't a number"):
        _select_indices("x", 4)


def test_form_collects_answers_and_reasks_on_bad_input() -> None:
    saved = ["henzie", "sauron", "galadriel", "tom-bombadil"]
    # Scripted answers: an out-of-range pod pick (re-asked), then a valid pod, winner, died-first,
    # end-turn, win-method, and an empty date (defaults to today).
    answers = iter([
        "1 9",          # bad: 9 out of range → re-ask
        "1 2 3",        # pod = henzie, sauron, galadriel
        "2",            # winner = sauron
        "3",            # died-first = galadriel
        "11",           # end turn
        "1",            # win method = beatdown (sorted methods: beatdown,combo,grind,other,stall)
        "",             # date → default today
    ])
    out: list[str] = []
    result = _collect_game_form(saved, lambda _prompt: next(answers), out.append)
    assert result is not None
    assert result["pod"] == ["henzie", "sauron", "galadriel"]
    assert result["winner"] == "sauron"
    assert result["died_first"] == "galadriel"
    assert result["end_turn"] == 11
    assert result["win_method"] == "beatdown"
    assert any("try again" in line for line in out)  # the bad pod pick was surfaced + re-asked


def test_form_cancels_on_blank_pod() -> None:
    answers = iter([""])  # blank at the pod step = cancel
    assert _collect_game_form(["a", "b"], lambda _p: next(answers), lambda _l: None) is None
