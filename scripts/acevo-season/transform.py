"""Turn captured AC EVO templates + one season round + passwords into the
final config dicts (ready to be blob-encoded by codec.py).

The schema is the deeply-nested, per-session shape captured in Task 2; see
FIELD_MAP.md for the exact dotted paths and documented ambiguities. Weather
and the track-path substitution are best-effort extrapolations from a single
clear-weather / single-track (Kyalami) capture -- see task-4-report.md.
"""

import copy


# Session-id -> which session_defaults bucket supplies its duration. The Race
# (id "2") is special-cased to round_cfg["race_minutes"] in the builder.
_DURATION_BUCKET = {"0": "practice", "1": "qualifying"}


def set_path(obj: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[k]        # raises KeyError if an intermediate key is missing
    cur[keys[-1]] = value


def _iter_sessions(sd: dict):
    """Yield (session_id, session_dict) for every session of every event."""
    for ev in sd["event_map"].values():
        for sid, session in ev["session_map"].items():
            yield sid, session


def _track_slug(track: str) -> str:
    """On-disk folder/file slug for a track display name.

    EXTRAPOLATION: the only captured sample is "Kyalami" -> "kyalami", so the
    derived rule is "lower-case the display name". Validated for single-word
    names only; tracks with spaces/punctuation (e.g. "Spa-Francorchamps") may
    need an explicit slug override -- flagged for the Task 6 spike.
    """
    return track.lower()


def _apply_track(session: dict, track: str) -> None:
    """Replace the display name AND every on-disk path field so no stale track
    reference survives.

    Captured Kyalami pattern (backslash-separated Windows paths):
        name            = "Kyalami"
        folder_path     = "content\\tracks\\kyalami"
        file_path       = "content\\tracks\\kyalami\\kyalami.scene"
        track_data_path = "content\\tracks\\kyalami\\kyalami.track"
    """
    slug = _track_slug(track)
    folder = "content\\tracks\\" + slug
    tcd = session["scene"]["track_content_data"]
    tcd["name"] = track
    tcd["folder_path"] = folder
    tcd["file_path"] = folder + "\\" + slug + ".scene"
    tcd["track_data_path"] = folder + "\\" + slug + ".track"


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
    set_path(out, "allowed_cars_list_full",
             [{"car_name": name, "ballast": 0, "restrictor": 0}
              for name in server["cars"]])
    return out


def build_seasondefinition(template: dict, round_cfg: dict,
                           session_defaults: dict, weather_defaults: dict) -> dict:
    out = copy.deepcopy(template)

    # Effective weather: round-level overrides win over season defaults.
    weather = dict(weather_defaults)
    weather.update(round_cfg.get("weather") or {})

    for sid, session in _iter_sessions(out):
        # --- track + layout ---
        _apply_track(session, round_cfg["track"])
        set_path(session, "scene.track_layout_name", round_cfg["layout"])

        # --- time of day ---
        set_path(session, "weather.initial_date_time.hour", round_cfg["hour_of_day"])

        # --- session duration (minutes -> milliseconds) ---
        if sid == "2":                       # Race
            minutes = round_cfg["race_minutes"]
        else:
            bucket = _DURATION_BUCKET[sid]
            minutes = session_defaults[bucket]["minutes"]
        set_path(session, "specialization.base.session_duration_ms", minutes * 60000)

        # --- best-effort weather (see report; extrapolated from clear-weather capture) ---
        set_path(session, "weather.static_data.static_weather.mean_ambient_temperature_c",
                 weather["ambient_temp"])
        set_path(session, "weather.static_data.static_weather.cloud_coverage",
                 weather["cloud_level"])
        set_path(session, "weather.static_data.static_weather.precipitation",
                 weather["rain"])
        set_path(session, "weather.static_data.static_weather.initial_global_wetness",
                 weather["rain"])
        set_path(session, "weather.static_data.static_weather.is_dynamic_weather",
                 weather["weather_randomness"] > 0)
        # weather_type enum left unchanged: the rain enum string is unknown.

        # --- grip (numeric only, if the season supplies it) ---
        if "initial_grip" in round_cfg:
            set_path(session, "dynamic_track_condition.initial_grip",
                     round_cfg["initial_grip"])
        # The InitialGrip_* enum string is left unchanged.

    return out
