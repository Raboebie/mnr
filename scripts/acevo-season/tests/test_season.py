import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from season import load_season, active_round, SeasonError

ROUNDS = [
    {"track": "silverstone", "date": "2026-07-27"},
    {"track": "spa", "date": "2026-08-03"},
    {"track": "imola", "date": "2026-08-10"},
]


def test_active_is_soonest_future_round():
    assert active_round(ROUNDS, datetime.date(2026, 7, 30))["track"] == "spa"


def test_active_on_race_day_is_that_round():
    assert active_round(ROUNDS, datetime.date(2026, 8, 3))["track"] == "spa"


def test_active_before_season_is_first_round():
    assert active_round(ROUNDS, datetime.date(2026, 7, 1))["track"] == "silverstone"


def test_active_after_season_is_last_round():
    assert active_round(ROUNDS, datetime.date(2026, 9, 1))["track"] == "imola"


def test_load_valid_example():
    data = load_season(str(Path(__file__).resolve().parents[1] / "seasons" / "example.yml"))
    assert data["rounds"] and "server" in data


def test_load_rejects_round_without_date(tmp_path):
    p = tmp_path / "bad.yml"
    p.write_text("server: {}\nsession_defaults: {}\nrounds:\n  - {track: spa}\n")
    with pytest.raises(SeasonError):
        load_season(str(p))
