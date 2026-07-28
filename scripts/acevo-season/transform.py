"""Build the AC EVO -serverconfig and -seasondefinition documents (ready to be
blob-encoded by codec.py) from one season round + the track map + passwords.

The seasondefinition schema is the *flat input* form the game server actually
accepts -- validated end-to-end against the live server on 2026-07-27 (boots,
binds the game port, registers to the Kunos lobby). It is NOT the deeply-nested
`event_map/session_map/scene` shape that appears in the server log (that is the
server's internal/expanded representation, which its input parser rejects field
by field). Schema and enum values are adopted from the reference implementation
github.com/zino1337/acevo-server (`scripts/launch_payloads.py`).

The serverconfig document is patched from the captured `serverconfig.template.json`
(the server accepts it as-is; validated in the same spike).
"""

import copy

# --- enum vocabularies (season.yml friendly value -> game token) ---
EVENT_TYPES = {
    "practice": "GameModeType_PRACTICE",
    "race weekend": "GameModeType_RACE_WEEKEND",
}
WEATHER_TYPES = {
    "clear": "GameModeSelectionWeatherType_CLEAR",
    "scattered clouds": "GameModeSelectionWeatherType_SCATTERED_CLOUDS",
    "broken clouds": "GameModeSelectionWeatherType_BROKEN_CLOUDS",
    "overcast": "GameModeSelectionWeatherType_OVERCAST",
    "drizzle": "GameModeSelectionWeatherType_DRIZZLE",
    "rain": "GameModeSelectionWeatherType_RAIN",
    "heavy rain": "GameModeSelectionWeatherType_HEAVY_RAIN",
    "damp": "GameModeSelectionWeatherType_DAMP",
}
WEATHER_BEHAVIOURS = {
    "static": "GameModeSelectionWeatherBehaviour_STATIC",
    "dynamic": "GameModeSelectionWeatherBehaviour_DYNAMIC",
}
INITIAL_GRIPS = {
    "green": "InitialGrip_GREEN",
    "fast": "InitialGrip_FAST",
    "optimum": "InitialGrip_OPTIMUM",
}
DURATION_TYPE_TIME = "GameModeSelectionDuration_TIME"

# game_config carries these four sessions in order; Race duration comes from the
# round, the others from session_defaults. Warmup defaults to 0 (disabled).
_SESSIONS = ("practice", "qualify", "warmup", "race")


def set_path(obj: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[k]        # raises KeyError if an intermediate key is missing
    cur[keys[-1]] = value


def _enum(mapping: dict, value: str, what: str) -> str:
    key = str(value).strip().lower()
    if key not in mapping:
        raise KeyError(f"unknown {what} '{value}'; valid: {', '.join(sorted(mapping))}")
    return mapping[key]


def session_time(hour: int) -> dict:
    return {"year": 2024, "month": 8, "day": 15,
            "hour": int(hour), "minute": 0, "second": 0, "time_multiplier": 1}


def build_serverconfig(template: dict, server: dict, passwords: dict) -> dict:
    out = copy.deepcopy(template)
    set_path(out, "server_name", server["name"])
    # All four transport ports share the single game port.
    port = server["game_port"]
    set_path(out, "server_tcp_listener_port", port)
    set_path(out, "server_tcp_internal_port", port)
    set_path(out, "server_udp_listener_port", port)
    set_path(out, "server_udp_internal_port", port)
    set_path(out, "server_http_port", server["http_port"])
    set_path(out, "max_players", server["max_players"])
    set_path(out, "driver_password", passwords["driver"])
    set_path(out, "admin_password", passwords["admin"])
    set_path(out, "spectator_password", passwords["spectator"])
    # Cars are a list of {car_name, ballast, restrictor} objects, not strings.
    # Optional: if the season omits `cars`, keep the template's captured list
    # (car internal-name mapping is a separate concern from this schema).
    if server.get("cars"):
        set_path(out, "allowed_cars_list_full",
                 [{"car_name": name, "ballast": 0, "restrictor": 0}
                  for name in server["cars"]])
    return out


def build_seasondefinition(round_cfg: dict, session_defaults: dict,
                           weather_defaults: dict, tracks: dict) -> dict:
    """Build the flat season_doc the server accepts as -seasondefinition input.

    round_cfg keys: track (a tracks.json slug), hour_of_day, race_minutes, and
      optional weather (a dict overriding weather_defaults) and grip.
    session_defaults: {practice|qualify|warmup: {minutes: N}}.
    weather_defaults / round weather: {type, behaviour, grip}.
    tracks: the tracks.json map (slug -> event dict).
    """
    slug = round_cfg["track"]
    if slug not in tracks:
        raise KeyError(f"unknown track slug '{slug}'; see tracks.json for valid slugs")
    event = dict(tracks[slug])

    weather = dict(weather_defaults)
    weather.update(round_cfg.get("weather") or {})
    hour = round_cfg["hour_of_day"]

    game_config = {
        "race_duration_type": DURATION_TYPE_TIME,
        "min_waiting_for_players": 60,
        "max_waiting_for_players": 60,
    }
    for name in _SESSIONS:
        if name == "race":
            minutes = round_cfg["race_minutes"]
        else:
            minutes = session_defaults.get(name, {}).get("minutes", 0)
        game_config[f"{name}_duration"] = int(minutes) * 60
        game_config[f"{name}_time_of_day"] = session_time(hour)
        game_config[f"{name}_overtime_waiting_next_session"] = 0
        game_config[f"{name}_max_wait_to_box"] = 0

    grip = round_cfg.get("grip", weather.get("grip", "green"))
    return {
        "game_type": EVENT_TYPES["race weekend"],
        "game_config": game_config,
        "event": event,
        "weather_type": _enum(WEATHER_TYPES, weather.get("type", "clear"), "weather type"),
        "weather_behaviour": _enum(WEATHER_BEHAVIOURS, weather.get("behaviour", "static"),
                                   "weather behaviour"),
        "initial_grip": _enum(INITIAL_GRIPS, grip, "initial grip"),
        "export_json": False,
    }
