# AC EVO config field map (paths confirmed against captured live config)

> **SUPERSEDED for seasondefinition (2026-07-27).** The `seasondefinition` section
> below describes the server's *internal/expanded* log representation, which the
> game's input parser REJECTS. The real `-seasondefinition` input is the flat
> `season_doc` schema (game_type / game_config / event / weather_type /
> weather_behaviour / initial_grip / export_json) — built by `transform.py` and
> validated live on 2026-07-27 (server boots + registers to the Kunos lobby).
> Schema source: github.com/zino1337/acevo-server. The `serverconfig` section
> below is still accurate.

## Source of the capture

The `AssettoCorsaEVOServer.exe` process was **not running** on `mnr-race` at
capture time (2026-07-27; `Get-CimInstance Win32_Process -Filter
"Name='AssettoCorsaEVOServer.exe'"` returned nothing). Per the brief's
fallback, the config was recovered from the launcher log instead:

    C:\Users\MNR\Saved Games\ACE-Server\Assetto Corsa EVO Server.txt

This log is from the server's last (and apparently still current — the file
was still being appended to as of 2026-07-26 15:07, well after the
2026-07-20 19:25 startup) launch. On startup the server pretty-prints both
decoded configs into the log verbatim, one JSON object per multi-line block,
each line individually timestamp-prefixed (`[2026-07-20 19:25:25.980]
[server] [info] `). The captured templates were reconstructed by stripping
that prefix from every line between the `Season Definition` / `Server
Config` marker lines and re-parsing the result as JSON — this is the
*decoded* JSON, not the original base64 blob (the process command line,
which carries the blob, was unavailable since the process wasn't running).

**Consequence for the fixture:** `tests/fixtures/seasondefinition.sample.blob`
is therefore not a byte-for-byte capture of the live `-seasondefinition`
command-line argument. It is the reconstructed live JSON, re-encoded through
`codec.py`'s `encode()` (base64 of a 4-byte big-endian length prefix +
zlib-deflated UTF-8 JSON) to produce a wire-format-valid blob. The codec
module's own docstring notes byte-identity with the GUI's output is neither
required nor attempted, so this is consistent with the documented contract —
but flagging it here since it's a step removed from a literal command-line
scrape. The **content** (track, sessions, weather, grip, etc.) is the real
live config; only the compression bytes are freshly generated rather than
lifted verbatim.

`serverconfig` has no equivalent fixture (not required by the brief — only
`seasondefinition` needs one, since it carries no secrets).

## serverconfig
(`scripts/acevo-season/templates/serverconfig.template.json`)

- server name:            `server_name`
- tcp listener port:      `server_tcp_listener_port`
- tcp internal port:      `server_tcp_internal_port`
- udp listener port:      `server_udp_listener_port`             (not in brief's list, but mirrors the tcp pair — same value in captured config: 34597)
- udp internal port:      `server_udp_internal_port`             (ditto)
- http port:              `server_http_port`
- max players:            `max_players`
- allowed cars:           `allowed_cars_list_full`               # list of `{car_name, ballast, restrictor}` objects
- results path:            `results_path`
- driver password:        `driver_password`                      → `__DRIVER_PASSWORD__` in template
- admin password:         `admin_password`                       → `__ADMIN_PASSWORD__` in template
- spectator password:     `spectator_password`                   → `__SPECTATOR_PASSWORD__` in template

Other top-level keys present in the captured config (not in the brief's
list, recorded for completeness/transform awareness): `launch_path`,
`netcode_update_interval`, `type` (e.g. `MultiplayerServerListSessionType_RANKED`),
`cycle`, `pi_min`, `pi_max`, `property_1`/`property_2`/`property_3`,
`entry_list_server_url`, `results_post_url`, `token`, `entry_list_path`,
`tuning_type`.

## seasondefinition
(`scripts/acevo-season/templates/seasondefinition.template.json`)

Top level: `season_type`, `gamemode_type`, `no_leaderboard`, `cycle`,
`name`, `event_map`, `entrylist`, `entrylist_file`, `entrylist_source`,
`event_mutable_data`, `event_results_map`, `season_cache`.

Sessions live at `event_map.<event_id>.session_map.<session_id>`. In the
captured config there is one event (`event_map.0`, name `"Race Weekend"`)
with three sessions keyed `"0"` = Practice, `"1"` = Qualifying, `"2"` = Race
(the object keys are strings; iteration order in the JSON is `1, 0, 2` but
the numeric key is what identifies the session — don't rely on encounter
order).

- track:                  `event_map.<id>.session_map.<id>.scene.track_content_data.name`               # e.g. "Kyalami"; also `.folder_path` / `.file_path` / `.track_data_path` give the on-disk paths
- layout:                 `event_map.<id>.session_map.<id>.scene.track_layout_name`                      # e.g. "GP"
- session set:            `event_map.<id>.session_map`                                                   # dict keyed by session id ("0","1","2"), not a list — see note above
- session duration:       `event_map.<id>.session_map.<id>.specialization.base.session_duration_ms`      # milliseconds; Practice/Qualifying use `TimeAttack.Specialization`, Race uses `InstantRace.Specialization`, but both nest `base.session_duration_ms` the same way
- session laps (race):    `event_map.<id>.session_map.<id>.specialization.base.session_laps`              # 0 for time-based Qualifying/Practice, 10 for the captured Race
- hour of day:            `event_map.<id>.session_map.<id>.weather.initial_date_time.hour`                # captured: Practice=10, Qualifying=11, Race=12 (also `.minute`, `.second`, `.year`/`.month`/`.day`)
- ambient temp:           `event_map.<id>.session_map.<id>.weather.static_data.static_weather.ambient_temperature_c`   # AMBIGUITY: captured value is `0` for every session; the seemingly-live value (23.3815117) is actually under the sibling key `mean_ambient_temperature_c` in the same object. Unclear from this single snapshot which one the game actually reads at runtime vs which is a baseline/mean used for dynamic weather — flagging both paths rather than guessing.
- track temp:             **no dedicated key found.** Searched the whole decoded JSON for `track_temp`/`road_temp`/similar — not present. The only temperature-like fields are `ambient_temperature_c` and `mean_ambient_temperature_c` under `static_data.static_weather` (see above). Do not invent a `track_temperature_c` path; if the transform needs to set track temp, it likely has to derive it from ambient (game-computed) rather than set a field directly — needs confirmation against actual AC EVO server docs/behavior before wiring the transform.
- cloud level:            `event_map.<id>.session_map.<id>.weather.static_data.static_weather.cloud_coverage`   # captured value 0 for all sessions (weather_type is `GameModeSelectionWeatherType_CLEAR`); related sibling fields in the same object: `gloominess`, `fog`, `humidity`, `pressure_psi`, `wind_speed_m_s`, `wind_gust`, `wind_direction_deg`, `initial_global_wetness`
- rain:                   **no `rain` key.** Closest analog is `static_weather.precipitation` (0 in the captured clear-weather config) and `initial_global_wetness`. Also `weather_type` at `event_map.<id>.session_map.<id>.weather_type` is the enum (`GameModeSelectionWeatherType_CLEAR` in this capture) that likely governs rain presence more than any numeric field — flagging both, no single obviously-correct path.
- weather randomness:     AMBIGUITY — no single "randomness" field. Candidates seen in the captured config, all siblings of `weather`: `weather.spatial_noise_data` (`scale`, `frequency`, `amplitude`, `order`, `seed.x`/`seed.y`) governs dynamic-weather spatial variation; `weather.static_data.static_weather.is_dynamic_weather` (bool, `false` here) toggles whether any randomness applies at all; `weather_update_interval_seconds` (0 here) and `weather.recalc_interval_seconds` (10) govern how often it's recalculated. Recording all four rather than picking one — needs a second live sample with dynamic weather enabled to disambiguate which one the transform should target.
- initial grip:           `event_map.<id>.session_map.<id>.initial_grip`                                  # enum string, captured: `"InitialGrip_GREEN"` for all sessions. AMBIGUITY: there is also a *numeric* grip at `event_map.<id>.session_map.<id>.dynamic_track_condition.initial_grip` (captured: `0.96` for all sessions) plus `.rubber` (0.2) and `.marbles` (0.12) in the same object — the enum and the float both exist side by side and both are called "initial_grip". Flagging both paths; the transform will need to decide (or set both) depending on which one AC EVO actually reads.

### Entry list
- `entrylist` (top-level) is a dict with `competitors` (list), `cars` (list),
  `drivers` (list) — captured config has a single placeholder competitor
  (`competitor_key: ""`, `name: "None"`) and empty `cars`/`drivers`. Not in
  the brief's field list but noted since it's the obvious hook point for
  entry-list automation later.
