import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transform import set_path, build_serverconfig, build_seasondefinition

SC_TEMPLATE = json.loads((ROOT / "templates" / "serverconfig.template.json").read_text())
SD_TEMPLATE = json.loads((ROOT / "templates" / "seasondefinition.template.json").read_text())


def _all_sessions(sd):
    for ev in sd["event_map"].values():
        for sid, s in ev["session_map"].items():
            yield sid, s


def test_set_path_nested():
    obj = {"a": {"b": {"c": 1}}}
    set_path(obj, "a.b.c", 99)
    assert obj["a"]["b"]["c"] == 99


def test_set_path_missing_intermediate_raises():
    with pytest.raises(KeyError):
        set_path({"a": {}}, "a.b.c", 1)


def test_build_serverconfig_ports_name_passwords_and_car_objects():
    template = copy.deepcopy(SC_TEMPLATE)
    original = copy.deepcopy(template)
    server = {"name": "MNR TEST", "game_port": 34597, "http_port": 8080,
              "max_players": 19, "cars": ["ferrari_296_gt3", "porsche_992_gt3"]}
    passwords = {"driver": "d1", "admin": "a1", "spectator": "s1"}
    out = build_serverconfig(template, server, passwords)
    assert template == original                                   # template not mutated
    assert out["server_name"] == "MNR TEST"
    assert out["server_tcp_listener_port"] == 34597 and out["server_tcp_internal_port"] == 34597
    assert out["server_udp_listener_port"] == 34597 and out["server_udp_internal_port"] == 34597
    assert out["driver_password"] == "d1" and out["admin_password"] == "a1" and out["spectator_password"] == "s1"
    assert "__DRIVER_PASSWORD__" not in json.dumps(out)
    cars = out["allowed_cars_list_full"]
    assert isinstance(cars, list) and cars
    assert all(isinstance(c, dict) and "car_name" in c for c in cars)
    assert {c["car_name"] for c in cars} == {"ferrari_296_gt3", "porsche_992_gt3"}


def test_build_seasondefinition_track_layout_hour_ms_per_session_no_stale_track():
    template = copy.deepcopy(SD_TEMPLATE)
    original = copy.deepcopy(template)
    round_cfg = {"track": "Spa", "layout": "GP", "hour_of_day": 17, "race_minutes": 30}
    session_defaults = {"practice": {"minutes": 240}, "qualifying": {"minutes": 15}, "race": {"minutes": 30}}
    weather_defaults = {"ambient_temp": 20, "cloud_level": 0.1, "rain": 0, "weather_randomness": 3}
    out = build_seasondefinition(template, round_cfg, session_defaults, weather_defaults)
    assert template == original                                   # template not mutated
    assert "Kyalami" not in json.dumps(out)                       # every track reference replaced
    expect_ms = {"0": 240 * 60000, "1": 15 * 60000, "2": 30 * 60000}
    seen = set()
    for sid, s in _all_sessions(out):
        seen.add(sid)
        assert s["scene"]["track_content_data"]["name"] == "Spa"
        assert s["scene"]["track_layout_name"] == "GP"
        assert s["weather"]["initial_date_time"]["hour"] == 17
        assert s["specialization"]["base"]["session_duration_ms"] == expect_ms[sid]
    assert seen == {"0", "1", "2"}
    assert "kyalami" not in json.dumps(out).lower()                # no stale slug anywhere, any case


def test_build_seasondefinition_best_effort_weather():
    template = copy.deepcopy(SD_TEMPLATE)
    round_cfg = {"track": "Spa", "layout": "GP", "hour_of_day": 17, "race_minutes": 30,
                 "weather": {"rain": 0.6, "cloud_level": 0.8}}
    session_defaults = {"practice": {"minutes": 240}, "qualifying": {"minutes": 15}, "race": {"minutes": 30}}
    weather_defaults = {"ambient_temp": 26, "cloud_level": 0.1, "rain": 0, "weather_randomness": 5}
    out = build_seasondefinition(template, round_cfg, session_defaults, weather_defaults)
    for _sid, s in _all_sessions(out):
        sw = s["weather"]["static_data"]["static_weather"]
        assert sw["mean_ambient_temperature_c"] == 26          # from weather_defaults
        assert sw["cloud_coverage"] == 0.8                     # round override wins
        assert sw["precipitation"] == 0.6                      # rain
        assert sw["is_dynamic_weather"] is True                # randomness 5 > 0
