import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transform import set_path, build_serverconfig, build_seasondefinition

SC_TEMPLATE = json.loads((ROOT / "templates" / "serverconfig.template.json").read_text())
TRACKS = json.loads((ROOT / "tracks.json").read_text())
SD = {"practice": {"minutes": 10}, "qualify": {"minutes": 10}, "warmup": {"minutes": 0}}
WD = {"type": "clear", "behaviour": "static", "grip": "green"}


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
    assert {c["car_name"] for c in cars} == {"ferrari_296_gt3", "porsche_992_gt3"}


def test_build_serverconfig_keeps_template_cars_when_omitted():
    template = copy.deepcopy(SC_TEMPLATE)
    orig_cars = copy.deepcopy(template["allowed_cars_list_full"])
    server = {"name": "x", "game_port": 34597, "http_port": 8080, "max_players": 19}
    out = build_serverconfig(template, server, {"driver": "d", "admin": "a", "spectator": "s"})
    assert out["allowed_cars_list_full"] == orig_cars             # captured list preserved


def test_build_seasondefinition_kyalami_gp_matches_validated_schema():
    r = {"track": "kyalami_gp", "hour_of_day": 12, "race_minutes": 30}
    out = build_seasondefinition(r, SD, WD, TRACKS)
    assert out["game_type"] == "GameModeType_RACE_WEEKEND"
    assert out["event"] == {"track": "Kyalami", "layout": "GP", "event_name": "GP Race",
                            "track_length": 4522, "max_pit_slot": 20}
    gc = out["game_config"]
    assert gc["race_duration"] == 30 * 60                         # seconds, from race_minutes
    assert gc["practice_duration"] == 10 * 60 and gc["qualify_duration"] == 10 * 60
    assert gc["warmup_duration"] == 0
    assert gc["race_duration_type"] == "GameModeSelectionDuration_TIME"
    assert gc["race_time_of_day"]["hour"] == 12 and gc["practice_time_of_day"]["hour"] == 12
    assert out["weather_type"] == "GameModeSelectionWeatherType_CLEAR"
    assert out["weather_behaviour"] == "GameModeSelectionWeatherBehaviour_STATIC"
    assert out["initial_grip"] == "InitialGrip_GREEN"
    assert out["export_json"] is False


def test_round_weather_and_grip_override():
    r = {"track": "spa_gp", "hour_of_day": 17, "race_minutes": 60,
         "weather": {"type": "rain"}, "grip": "optimum"}
    out = build_seasondefinition(r, SD, WD, TRACKS)
    assert out["event"]["track"] == "Circuit de Spa Francorchamps"
    assert out["weather_type"] == "GameModeSelectionWeatherType_RAIN"
    assert out["initial_grip"] == "InitialGrip_OPTIMUM"
    assert out["game_config"]["race_duration"] == 60 * 60


def test_unknown_track_raises():
    with pytest.raises(KeyError):
        build_seasondefinition({"track": "silverstone_gp", "hour_of_day": 12, "race_minutes": 30},
                               SD, WD, TRACKS)


def test_unknown_weather_type_raises():
    with pytest.raises(KeyError):
        build_seasondefinition({"track": "kyalami_gp", "hour_of_day": 12, "race_minutes": 30,
                                "weather": {"type": "snow"}}, SD, WD, TRACKS)
