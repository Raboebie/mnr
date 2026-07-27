# AC EVO Season Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the AC EVO dedicated server's configuration as a season-of-rounds calendar, apply the active round automatically each week, and run the server as an NSSM Windows service.

**Architecture:** A workstation Python toolkit (`scripts/acevo-season/`) turns a `season.yml` into the two base64/zlib command-line blobs AC EVO needs, by transforming captured live config templates. Ansible pushes the generated blobs to `mnr-race`; an NSSM service runs `AssettoCorsaEVOServer.exe` directly via a wrapper that reads the blobs from files; a daily `rotate.ps1` swaps in the active round's blob and restarts only on change.

**Tech Stack:** Python 3 (stdlib + PyYAML), pytest, PowerShell + NSSM on Windows, Ansible over WinRM, ansible-vault.

## Global Constraints

- **Blob wire format:** `base64( 4-byte big-endian uncompressed-JSON length + zlib.deflate(JSON) )`. Semantic round-trip only — byte-identity of the encoded blob is NOT required or targeted.
- **Python:** stdlib + PyYAML only (PyYAML ships with Ansible; no other third-party runtime deps). Tests use `pytest`.
- **Server (mnr-race, 10.104.0.10):** Windows, reached via WinRM over the JH1 OpenVPN tunnel. All `ansible`/`ansible-playbook` runs from `ansible/`, prefixed on macOS with `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`.
- **Install dir:** `C:\Users\MNR\Desktop\mnr\ACEvo_Latest`. Automation dir: `…\ACEvo_Latest\automation\`.
- **Game exe:** `AssettoCorsaEVOServer.exe`. GUI launcher `ServerLauncher.exe` is bypassed at runtime.
- **Ports:** game 34597 (TCP+UDP, listener and internal both), HTTP 8080. Max players 19.
- **Service:** NSSM service `acevo-server`, `Automatic` start, crash-restart, runs as `MNR-RACE\MNR`, AppDirectory = install dir. Reuse `C:\palace\tools\nssm.exe`.
- **Rotation:** scheduled task `AcevoRoundRotate`, daily **05:00 SAST**, runs `rotate.ps1`; restart only if the active round's blob changed.
- **Active round rule:** the soonest round whose `date ≥ today`; after the final round, keep the last round.
- **Secrets:** driver/admin/spectator passwords from `vault_acevo_driver_password` / `vault_acevo_admin_password` / `vault_acevo_spectator_password`. Templates are secret-free (placeholders). **Generated `*.blob` files contain plaintext passwords and are gitignored — never committed.**
- **Spec:** `docs/superpowers/specs/2026-07-27-acevo-season-automation-design.md`.

---

### Task 1: Blob codec

**Files:**
- Create: `scripts/acevo-season/codec.py`
- Test: `scripts/acevo-season/tests/test_codec.py`
- Modify: `scripts/acevo-decode-launch.py` (import the shared codec instead of duplicating the format)

**Interfaces:**
- Produces: `codec.encode(obj: object) -> str`, `codec.decode(blob: str) -> object` (raises `ValueError` on a length-prefix/zlib mismatch).

- [ ] **Step 1: Write the failing tests**

```python
# scripts/acevo-season/tests/test_codec.py
import base64
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codec import encode, decode


def test_semantic_round_trip():
    obj = {
        "name": "MNR | Monday Night Racing",
        "port": 34597,
        "cars": ["ferrari_296", "porsche_992"],
        "nested": {"temp": 24.5, "rain": 0.0, "enabled": True},
    }
    assert decode(encode(obj)) == obj


def test_length_prefix_is_uncompressed_length():
    obj = {"k": "v" * 5000}
    raw = base64.b64decode(encode(obj))
    declared = struct.unpack(">I", raw[:4])[0]
    expected = len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert declared == expected


def test_decode_rejects_length_mismatch():
    data = json.dumps({"a": 1}).encode("utf-8")
    import zlib
    bad = base64.b64encode(struct.pack(">I", len(data) + 5) + zlib.compress(data)).decode("ascii")
    with pytest.raises(ValueError):
        decode(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_codec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codec'`.

- [ ] **Step 3: Write the codec**

```python
# scripts/acevo-season/codec.py
"""AC EVO launch-blob wire format.

A blob is base64 of: 4-byte big-endian uncompressed-JSON length, then
zlib-deflated UTF-8 JSON. The server only needs our blob to *decode* to the
intended JSON; byte-identity with the GUI's output is neither required nor
attempted.
"""
import base64
import json
import struct
import zlib


def decode(blob: str) -> object:
    raw = base64.b64decode(blob)
    declared = struct.unpack(">I", raw[:4])[0]
    data = zlib.decompress(raw[4:])
    if len(data) != declared:
        raise ValueError(f"length prefix {declared} != actual {len(data)}")
    return json.loads(data)


def encode(obj: object) -> str:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = struct.pack(">I", len(data)) + zlib.compress(data, 9)
    return base64.b64encode(payload).decode("ascii")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_codec.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Refactor `acevo-decode-launch.py` to use the shared codec**

Replace its local `decode()` body (the base64/struct/zlib block) with an import. At the top, after the existing imports, add:

```python
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "acevo-season"))
from codec import decode as _decode  # noqa: E402
```

Replace the whole `def decode(blob): ...` function with:

```python
def decode(blob: str):
    return _decode(blob)
```

- [ ] **Step 6: Verify the decoder CLI still works**

Run: `python3 scripts/acevo-decode-launch.py "$(cd scripts/acevo-season && python3 -c 'from codec import encode; print(encode({"hello": "world"}))')"`
Expected: prints `===== blob 1 =====` then `{ "hello": "world" }`.

- [ ] **Step 7: Commit**

```bash
git add scripts/acevo-season/codec.py scripts/acevo-season/tests/test_codec.py scripts/acevo-decode-launch.py
git commit -m "feat(acevo): add blob codec; decode CLI uses it"
```

---

### Task 2: Capture live config → secret-free templates + vault passwords

This is a **discovery task** (no TDD): it produces the real templates the transform will patch, a real-blob decode fixture, the field-path map, and the vault password entries. Requires the VPN up and WinRM reachable (`ansible windows -m win_ping` returns `pong`).

**Files:**
- Create: `scripts/acevo-season/templates/serverconfig.template.json` (secret-free)
- Create: `scripts/acevo-season/templates/seasondefinition.template.json`
- Create: `scripts/acevo-season/tests/fixtures/seasondefinition.sample.blob` (real captured blob, secret-free config only — the seasondefinition has no passwords)
- Create: `scripts/acevo-season/FIELD_MAP.md`
- Modify: `ansible/group_vars/all/vault.yml` (add the three password vars)

- [ ] **Step 1: Capture the live launch command**

The live blobs are on the process command line. Run (from `ansible/`):

```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible windows -m win_shell -a \
  '(Get-CimInstance Win32_Process -Filter "Name=''AssettoCorsaEVOServer.exe''").CommandLine' \
  2>&1 | grep -v '^objc\|fork()\|breakpoint'
```

Expected: a long line containing `-serverconfig <blob> -seasondefinition <blob>`.
If no process is running, fall back to the launcher log `serverConfig\Assetto Corsa EVO Server.txt` (the config JSON is echoed there) or `Backup_2026-06-06\ac_evo_launch.bat` as a last resort (stale — note it in FIELD_MAP.md).

- [ ] **Step 2: Decode both blobs locally**

Save the command line to `/tmp/acevo_cmd.txt`, then:

```bash
python3 scripts/acevo-decode-launch.py --bat /tmp/acevo_cmd.txt > /tmp/acevo_decoded.txt
```

Expected: two JSON sections, `===== serverconfig =====` and `===== seasondefinition =====`.

- [ ] **Step 3: Create the seasondefinition template + fixture**

Copy the decoded `seasondefinition` JSON verbatim to `scripts/acevo-season/templates/seasondefinition.template.json`. Save the raw `seasondefinition` blob string to `scripts/acevo-season/tests/fixtures/seasondefinition.sample.blob`. (The seasondefinition carries no secrets.)

- [ ] **Step 4: Create the secret-free serverconfig template**

Copy the decoded `serverconfig` JSON to `scripts/acevo-season/templates/serverconfig.template.json`, then **replace the three password values** with placeholders `__DRIVER_PASSWORD__`, `__ADMIN_PASSWORD__`, `__SPECTATOR_PASSWORD__`. Confirm with `grep -i password` that no real secret remains before saving.

- [ ] **Step 5: Record the field map**

Create `scripts/acevo-season/FIELD_MAP.md` documenting the exact dotted JSON paths (as seen in the captured templates) for every field the tooling overrides. Fill in the real paths — examples of the entries required (confirm each against the captured JSON, the key names below are illustrative until confirmed):

```markdown
# AC EVO config field map (paths confirmed against captured live config)

## serverconfig
- server name:            <path>          # e.g. serverName
- tcp listener port:      <path>          # server_tcp_listener_port
- tcp internal port:      <path>          # server_tcp_internal_port
- http port:              <path>
- max players:            <path>
- allowed cars:           <path>          # list
- results path:           <path>
- driver password:        <path>
- admin password:         <path>
- spectator password:     <path>

## seasondefinition
- track:                  <path>
- layout:                 <path>
- session set:            <path>          # list of sessions
- session duration:       <path-within-session>
- hour of day:            <path>
- ambient temp:           <path>
- track temp:             <path>
- cloud level:            <path>
- rain:                   <path>
- weather randomness:     <path>
- initial grip:           <path>
```

- [ ] **Step 6: Store the real passwords in the vault**

Use the non-interactive editor pattern (from the cert work). Read the three real passwords out of `/tmp/acevo_decoded.txt`, then add to `vault.yml`:

```bash
cd ansible
cat > /tmp/vault_add.py <<'PY'
import sys
p = sys.argv[1]
add = (
    'vault_acevo_driver_password: "DRIVER_HERE"\n'
    'vault_acevo_admin_password: "ADMIN_HERE"\n'
    'vault_acevo_spectator_password: "SPECTATOR_HERE"\n'
)
s = open(p).read()
if 'vault_acevo_driver_password' not in s:
    open(p, 'w').write(s.rstrip() + '\n' + add)
PY
# hand-edit /tmp/vault_add.py to paste the three real values, then:
EDITOR="python3 /tmp/vault_add.py" ansible-vault edit group_vars/all/vault.yml
ansible-vault view group_vars/all/vault.yml | grep vault_acevo   # verify present
rm -f /tmp/vault_add.py /tmp/acevo_cmd.txt /tmp/acevo_decoded.txt
```

Expected: three `vault_acevo_*_password` lines present; `head -1 group_vars/all/vault.yml` still shows `$ANSIBLE_VAULT`.

- [ ] **Step 7: Add a decode-fixture test**

```python
# append to scripts/acevo-season/tests/test_codec.py
def test_decode_real_captured_blob():
    blob = (Path(__file__).parent / "fixtures" / "seasondefinition.sample.blob").read_text().strip()
    obj = decode(blob)
    assert isinstance(obj, dict) and obj  # non-empty dict
```

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_codec.py -v`
Expected: PASS (4 passed).

- [ ] **Step 8: Commit (templates + fixture + field map only — vault committed separately at deploy)**

```bash
git add scripts/acevo-season/templates scripts/acevo-season/tests/fixtures \
        scripts/acevo-season/FIELD_MAP.md scripts/acevo-season/tests/test_codec.py
git commit -m "feat(acevo): capture live config as secret-free templates + field map"
git add ansible/group_vars/all/vault.yml
git commit -m "chore(acevo): add acevo password vars to vault"
```

---

### Task 3: Season model + active-round selection

**Files:**
- Create: `scripts/acevo-season/season.py`
- Test: `scripts/acevo-season/tests/test_season.py`
- Create: `scripts/acevo-season/seasons/example.yml`

**Interfaces:**
- Produces: `season.load_season(path: str) -> dict` (raises `season.SeasonError`); `season.active_round(rounds: list, today: datetime.date) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# scripts/acevo-season/tests/test_season.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_season.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'season'`.

- [ ] **Step 3: Write `season.py`**

```python
# scripts/acevo-season/season.py
import datetime
import yaml


class SeasonError(Exception):
    pass


def load_season(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SeasonError("season file is not a mapping")
    for key in ("server", "session_defaults", "rounds"):
        if key not in data:
            raise SeasonError(f"missing top-level key: {key}")
    if not data["rounds"]:
        raise SeasonError("rounds is empty")
    for i, r in enumerate(data["rounds"], 1):
        for key in ("track", "date"):
            if key not in r:
                raise SeasonError(f"round {i} missing '{key}'")
        try:
            datetime.date.fromisoformat(r["date"])
        except ValueError as exc:
            raise SeasonError(f"round {i} bad date: {exc}") from exc
    return data


def active_round(rounds: list, today: datetime.date) -> dict:
    dated = sorted(rounds, key=lambda r: datetime.date.fromisoformat(r["date"]))
    upcoming = [r for r in dated if datetime.date.fromisoformat(r["date"]) >= today]
    return upcoming[0] if upcoming else dated[-1]
```

- [ ] **Step 4: Write `seasons/example.yml`**

```yaml
# scripts/acevo-season/seasons/example.yml
# Worked example. Track/layout/weather key names mirror FIELD_MAP.md.
server:
  name: "MNR | Monday Night Racing"
  game_port: 34597
  http_port: 8080
  max_players: 19
  cars: [ferrari_296_gt3, porsche_992_gt3]

race_start_time: "18:00:00+02:00"

session_defaults:
  practice:   {minutes: 240}
  qualifying: {minutes: 15}
  race:       {minutes: 30}

# Weather vocabulary maps best-effort onto the real (nested) fields per FIELD_MAP.md.
# No `track_temp` — AC EVO has no such field (game-derived). `rain` (0..1) drives
# precipitation + initial_global_wetness; `weather_randomness` drives dynamic weather.
weather_defaults:
  ambient_temp: 24
  cloud_level: 0.05
  rain: 0
  weather_randomness: 4

rounds:
  - {track: silverstone, layout: gp, hour_of_day: 21, race_minutes: 30, date: "2026-07-27"}
  - {track: spa,         layout: gp, hour_of_day: 17, race_minutes: 30, date: "2026-08-03"}
  - {track: imola,       layout: gp, hour_of_day: 7,  race_minutes: 60, date: "2026-08-10"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_season.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add scripts/acevo-season/season.py scripts/acevo-season/tests/test_season.py scripts/acevo-season/seasons/example.yml
git commit -m "feat(acevo): season model + active-round selection"
```

---

### Task 4: Config transform

Turns the captured templates + a season round + passwords into the final config dicts. **The real schema (from Task 2's capture / `FIELD_MAP.md`) is deeply nested and per-session** — this task was revised after the capture. Read `scripts/acevo-season/FIELD_MAP.md` and the two committed templates before writing code; bind every exact path from FIELD_MAP, do not guess.

**Files:**
- Create: `scripts/acevo-season/transform.py`
- Test: `scripts/acevo-season/tests/test_transform.py`

**Real-schema facts you must honor (from FIELD_MAP.md):**
- **serverconfig** top-level keys: `server_name`, `server_tcp_listener_port`, `server_tcp_internal_port`, `server_udp_listener_port`, `server_udp_internal_port` (all four ports = `server["game_port"]`), `server_http_port`, `max_players`, `results_path` (leave as-is), `driver_password` / `admin_password` / `spectator_password`. Cars live in **`allowed_cars_list_full`** — a **list of objects** `{"car_name": <str>, "ballast": 0, "restrictor": 0}`, NOT plain strings. Expand `server["cars"]` (a list of names) into that object shape (ballast/restrictor default 0).
- **seasondefinition** config is **per-session**, nested at `event_map.<eid>.session_map.<sid>` (session ids are the strings `"0"`=Practice, `"1"`=Qualifying, `"2"`=Race). Iterate every event and every session. Per session set:
  - track: `scene.track_content_data.name` **and** the sibling on-disk path fields (`folder_path`, `file_path`, `track_data_path`) — derive the new track's path strings by substituting into the pattern the captured **Kyalami** values show (read them from the template). The golden test asserts **no stale `"Kyalami"` remains anywhere**, which forces you to replace every track reference, not just `.name`.
  - layout: `scene.track_layout_name`.
  - time of day: `weather.initial_date_time.hour` = `round_cfg["hour_of_day"]`.
  - duration: `specialization.base.session_duration_ms` = minutes × 60000 (Practice/Qualifying from `session_defaults`, Race from `round_cfg["race_minutes"]`).
- **Weather — best-effort** (user chose this; the single captured sample is clear-weather so these are extrapolations to validate at the spike). Under each session's `weather.static_data.static_weather`: `mean_ambient_temperature_c` = `ambient_temp`; `cloud_coverage` = `cloud_level`; `precipitation` and `initial_global_wetness` = `rain`; `is_dynamic_weather` = `(weather_randomness > 0)`. Leave `weather_type` enum unchanged (the rain enum string is unknown — document this). Optionally scale `weather.spatial_noise_data.amplitude` by `weather_randomness` if present. Grip: set the numeric `dynamic_track_condition.initial_grip` from `round_cfg["initial_grip"]` if the season provides it; leave the `initial_grip` enum string. Document every best-effort choice in your report.

**Interfaces (unchanged from the pre-revision plan — Task 5 depends on these signatures):**
- `transform.set_path(obj: dict, path: str, value) -> None` (mutates in place; raises `KeyError` if an intermediate key is missing)
- `transform.build_serverconfig(template: dict, server: dict, passwords: dict) -> dict`
- `transform.build_seasondefinition(template: dict, round_cfg: dict, session_defaults: dict, weather_defaults: dict) -> dict`
- Both builders return a deep-copied, patched dict (template not mutated). `server` has keys `name, game_port, http_port, max_players, cars`. `passwords` has keys `driver, admin, spectator`. `round_cfg` has `track, layout, hour_of_day, race_minutes` and optional `weather`, `initial_grip`. `weather_defaults` has `ambient_temp, cloud_level, rain, weather_randomness`.

- [ ] **Step 1: Write the failing tests (mechanism + golden against the REAL template)**

```python
# scripts/acevo-season/tests/test_transform.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'transform'`.

- [ ] **Step 3: Write `transform.py`**

Read `FIELD_MAP.md` and both templates first. Implement to the facts above and the golden tests. Structure it as: a `set_path` helper (below, complete), a small per-session iterator, an `_apply_track` helper that replaces name + all path fields (derive the pattern from the captured Kyalami values you read in the template), and the two `build_*` functions. Bind every path from FIELD_MAP — do not invent keys. `set_path` is fully specified; the rest you write against the real template:

```python
def set_path(obj: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[k]        # raises KeyError if an intermediate key is missing
    cur[keys[-1]] = value
```

Requirements the code must meet (the golden tests enforce most of these):
- `build_serverconfig`: deep-copy; set `server_name`, all four port fields (= `game_port`), `server_http_port`, `max_players`, the three passwords; replace `allowed_cars_list_full` with `[{"car_name": n, "ballast": 0, "restrictor": 0} for n in server["cars"]]`. Do not mutate the input template.
- `build_seasondefinition`: deep-copy; iterate `event_map.*.session_map.*`; per session set track (name + path fields via `_apply_track`, leaving **no** stale `"Kyalami"`), layout, `weather.initial_date_time.hour`, and `specialization.base.session_duration_ms` (minutes×60000; Race = session id `"2"` uses `round_cfg["race_minutes"]`, `"0"`→practice, `"1"`→qualifying from `session_defaults`); apply best-effort weather (`mean_ambient_temperature_c`, `cloud_coverage`, `precipitation`, `initial_global_wetness`, `is_dynamic_weather`) with `round_cfg["weather"]` overriding `weather_defaults`; set numeric `dynamic_track_condition.initial_grip` if `round_cfg` provides `initial_grip`. Do not mutate the input template.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_transform.py -v`
Expected: PASS (5 passed). If a golden test fails, your paths don't match the real template — fix the paths from `FIELD_MAP.md`, **do not weaken the test** (in particular the "no stale Kyalami" and per-session ms assertions).

- [ ] **Step 5: Commit and report extrapolations**

```bash
git add scripts/acevo-season/transform.py scripts/acevo-season/tests/test_transform.py
git commit -m "feat(acevo): config transform (real per-session schema, best-effort weather)"
```

In your report, list every extrapolation/best-effort decision (the derived track-path pattern + casing assumption, which ambient/rain/randomness fields you targeted, what you left unchanged like `weather_type`), and mark the task **DONE_WITH_CONCERNS** — these get validated at the Task 6 spike.

---

### Task 5: `gen.py` CLI + manifest + gitignore

**Files:**
- Create: `scripts/acevo-season/gen.py`
- Test: `scripts/acevo-season/tests/test_gen.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `codec`, `season`, `transform`.
- Produces (in `--out` dir): `serverconfig.blob`, `round-NN.blob` (one per round, 1-based, zero-padded to 2), `manifest.json` (`[{"round":1,"date":"YYYY-MM-DD","blob":"round-01.blob"}, ...]`). Also `gen.py --active-round --season X` prints the active round number for today.
- Password env vars: `ACEVO_DRIVER_PASSWORD`, `ACEVO_ADMIN_PASSWORD`, `ACEVO_SPECTATOR_PASSWORD`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/acevo-season/tests/test_gen.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codec import decode


def test_gen_emits_blobs_and_manifest(tmp_path):
    out = tmp_path / "out"
    import os
    env = {**os.environ,
           "ACEVO_DRIVER_PASSWORD": "DRV_9f3", "ACEVO_ADMIN_PASSWORD": "ADM_9f3",
           "ACEVO_SPECTATOR_PASSWORD": "SPC_9f3"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "gen.py"),
         "--season", str(ROOT / "seasons" / "example.yml"),
         "--templates", str(ROOT / "templates"),
         "--out", str(out)],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest) == 3                           # example.yml has 3 rounds
    assert [e["round"] for e in manifest] == [1, 2, 3]
    assert (out / "serverconfig.blob").exists()
    for entry in manifest:
        blob = (out / entry["blob"]).read_text().strip()
        assert isinstance(decode(blob), dict)          # every round blob decodes
    # distinctive passwords land in the exact serverconfig fields
    sc = decode((out / "serverconfig.blob").read_text().strip())
    assert sc["driver_password"] == "DRV_9f3"
    assert sc["admin_password"] == "ADM_9f3"
    assert sc["spectator_password"] == "SPC_9f3"
    # a later round's track appears in its own blob (round 2 of example.yml is spa)
    sd2 = decode((out / manifest[1]["blob"]).read_text().strip())
    assert "spa" in json.dumps(sd2).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_gen.py -v`
Expected: FAIL — gen.py missing (non-zero returncode / file not found).

- [ ] **Step 3: Write `gen.py`**

```python
# scripts/acevo-season/gen.py
"""Generate AC EVO launch blobs from a season.yml."""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from codec import encode
from season import load_season, active_round
from transform import build_serverconfig, build_seasondefinition


def _passwords_from_env() -> dict:
    return {
        "driver": os.environ["ACEVO_DRIVER_PASSWORD"],
        "admin": os.environ["ACEVO_ADMIN_PASSWORD"],
        "spectator": os.environ["ACEVO_SPECTATOR_PASSWORD"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True)
    ap.add_argument("--templates", required=True)
    ap.add_argument("--out")
    ap.add_argument("--active-round", action="store_true",
                    help="print today's active round number and exit")
    args = ap.parse_args()

    data = load_season(args.season)

    if args.active_round:
        today = datetime.date.today()
        ar = active_round(data["rounds"], today)
        print(data["rounds"].index(ar) + 1)
        return 0

    tdir = Path(args.templates)
    sc_template = json.loads((tdir / "serverconfig.template.json").read_text())
    sd_template = json.loads((tdir / "seasondefinition.template.json").read_text())

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sc = build_serverconfig(sc_template, data["server"], _passwords_from_env())
    (out / "serverconfig.blob").write_text(encode(sc))

    manifest = []
    for i, r in enumerate(data["rounds"], 1):
        sd = build_seasondefinition(sd_template, r, data["session_defaults"],
                                    data.get("weather_defaults", {}))
        name = f"round-{i:02d}.blob"
        (out / name).write_text(encode(sd))
        manifest.append({"round": i, "date": r["date"], "blob": name})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(manifest)} round blobs + serverconfig + manifest to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts/acevo-season && python3 -m pytest tests/test_gen.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Add gitignore for generated blobs**

Append to `.gitignore`:

```
# AC EVO generated launch blobs contain plaintext passwords — never commit
scripts/acevo-season/**/*.blob
!scripts/acevo-season/tests/fixtures/*.blob
scripts/acevo-season/out/
```

(The `!` re-includes the secret-free decode fixture from Task 2.)

- [ ] **Step 6: Run the full Python suite + verify gitignore**

Run: `cd scripts/acevo-season && python3 -m pytest -v`
Expected: PASS (all tasks' tests, ~15 passed).
Run: `cd /Users/dihankapp/git/fun/mnr && ACEVO_DRIVER_PASSWORD=x ACEVO_ADMIN_PASSWORD=x ACEVO_SPECTATOR_PASSWORD=x python3 scripts/acevo-season/gen.py --season scripts/acevo-season/seasons/example.yml --templates scripts/acevo-season/templates --out scripts/acevo-season/out && git status --porcelain scripts/acevo-season/out`
Expected: gen prints its summary; `git status` shows **no** output for `out/` (ignored).

- [ ] **Step 7: Commit**

```bash
git add scripts/acevo-season/gen.py scripts/acevo-season/tests/test_gen.py .gitignore
git commit -m "feat(acevo): gen.py CLI (season -> blobs + manifest); gitignore blobs"
```

---

### Task 6: Validation spike — direct headless launch (GO/NO-GO GATE)

**No code.** Proves `AssettoCorsaEVOServer.exe` runs with our generated blobs, GUI bypassed. **Tasks 7–8 are blocked until this passes.** Requires VPN + an off-peak window (this starts a real server instance).

- [ ] **Step 1: Generate a real blob pair**

From the repo root, with the real passwords exported from the vault:

```bash
cd ansible
export ACEVO_DRIVER_PASSWORD=$(ansible-vault view group_vars/all/vault.yml | awk -F'"' '/vault_acevo_driver_password/{print $2}')
export ACEVO_ADMIN_PASSWORD=$(ansible-vault view group_vars/all/vault.yml | awk -F'"' '/vault_acevo_admin_password/{print $2}')
export ACEVO_SPECTATOR_PASSWORD=$(ansible-vault view group_vars/all/vault.yml | awk -F'"' '/vault_acevo_spectator_password/{print $2}')
cd ..
python3 scripts/acevo-season/gen.py --season scripts/acevo-season/seasons/example.yml \
  --templates scripts/acevo-season/templates --out scripts/acevo-season/out
```

- [ ] **Step 2: Stage the two blobs on the server**

Push `out/serverconfig.blob` and `out/round-01.blob` to `C:\Windows\Temp\acevo-spike\` via `win_copy` (forward-slash dest). Confirm both arrived (`Test-Path`).

- [ ] **Step 3: Confirm the launcher/server is currently stopped, then direct-launch**

Check `Get-Process ServerLauncher,AssettoCorsaEVOServer` — if the hand-started server is up, coordinate an off-peak window and stop it first. Then, in a SYSTEM/MNR interactive-ish run via `win_shell`, launch the exe directly:

```powershell
$dir = 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest'
$sc = (Get-Content 'C:\Windows\Temp\acevo-spike\serverconfig.blob' -Raw).Trim()
$sd = (Get-Content 'C:\Windows\Temp\acevo-spike\round-01.blob' -Raw).Trim()
Start-Process -FilePath (Join-Path $dir 'AssettoCorsaEVOServer.exe') `
  -ArgumentList @('-serverconfig', $sc, '-seasondefinition', $sd) -WorkingDirectory $dir
Start-Sleep 20
Get-Process AssettoCorsaEVOServer -ErrorAction SilentlyContinue | Select Id,StartTime
```

- [ ] **Step 4: Verify it came up healthy**

Tail `serverConfig\Assetto Corsa EVO Server.txt` and confirm: it parsed the config (server name = "MNR | Monday Night Racing"), bound game port 34597, and **connected the Kunos lobby websocket** (`wss://c.gk.sd:6990/...`). The `Could not bind TCP listener socket` line is known-benign noise.

- [ ] **Step 5: Record the outcome and stop the spike instance**

```powershell
Stop-Process -Name AssettoCorsaEVOServer -Force -ErrorAction SilentlyContinue
Remove-Item C:\Windows\Temp\acevo-spike -Recurse -Force
```

Write the result into the spec's Risks table (edit `docs/superpowers/specs/2026-07-27-acevo-season-automation-design.md`): **PASS** → proceed to Task 7; **FAIL** → stop, report, and switch to the config-gen-only fallback (drop Tasks 7–8's service work; keep gen + a "write blobs, you launch via the GUI" deploy). Commit the spec note.

```bash
git add docs/superpowers/specs/2026-07-27-acevo-season-automation-design.md
git commit -m "docs(acevo): record direct-launch validation-spike result"
```

---

### Task 7: NSSM service + wrapper + service playbook

**Gated on Task 6 = PASS.**

**Files:**
- Create: `scripts/acevo-season/server/run-acevo.ps1`
- Create: `ansible/deploy-acevo-service.yml`
- Modify: `ansible/group_vars/all/vars.yml` (add an `acevo:` block)

- [ ] **Step 1: Add the `acevo` vars block**

Append to `ansible/group_vars/all/vars.yml`:

```yaml
# AC EVO dedicated server (season automation)
acevo:
  install_dir: 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest'
  automation_dir: 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest\automation'
  exe: 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest\AssettoCorsaEVOServer.exe'
  service_name: acevo-server
  nssm: 'C:\palace\tools\nssm.exe'
  run_as: 'MNR-RACE\MNR'
```

- [ ] **Step 2: Write the wrapper**

```powershell
# scripts/acevo-season/server/run-acevo.ps1
# NSSM entrypoint. Reads the two live blob files and execs the game server.
# Blocks until the server exits so NSSM can restart-on-crash.
$ErrorActionPreference = 'Stop'
$dir  = 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest'
$auto = Join-Path $dir 'automation'
$sc = (Get-Content (Join-Path $auto 'serverconfig.blob')    -Raw).Trim()
$sd = (Get-Content (Join-Path $auto 'seasondefinition.blob') -Raw).Trim()
$exe = Join-Path $dir 'AssettoCorsaEVOServer.exe'
Set-Location $dir
& $exe -serverconfig $sc -seasondefinition $sd
exit $LASTEXITCODE
```

- [ ] **Step 3: Write `deploy-acevo-service.yml`**

```yaml
# ansible/deploy-acevo-service.yml
- name: Install the AC EVO NSSM service
  hosts: windows
  gather_facts: false
  vars:
    auto: "{{ acevo.automation_dir }}"
  tasks:
    - name: Ensure automation dir
      ansible.windows.win_file:
        path: "{{ auto }}"
        state: directory

    - name: Push the NSSM wrapper
      ansible.windows.win_copy:
        src: ../scripts/acevo-season/server/run-acevo.ps1
        dest: "{{ auto }}\\run-acevo.ps1"

    - name: Create / reconfigure the acevo-server service
      ansible.windows.win_shell: |
        $n = '{{ acevo.nssm }}'; $svc = '{{ acevo.service_name }}'
        $existing = & $n status $svc 2>$null
        if ($LASTEXITCODE -ne 0) {
          & $n install $svc 'powershell.exe' '-NoProfile -ExecutionPolicy Bypass -File "{{ auto }}\run-acevo.ps1"'
        } else {
          & $n set $svc Application 'powershell.exe'
          & $n set $svc AppParameters '-NoProfile -ExecutionPolicy Bypass -File "{{ auto }}\run-acevo.ps1"'
        }
        & $n set $svc AppDirectory '{{ acevo.install_dir }}'
        & $n set $svc Start SERVICE_AUTO_START
        & $n set $svc AppExit Default Restart
        & $n set $svc AppStopMethodConsole 1500
        & $n set $svc ObjectName '{{ acevo.run_as }}' '{{ vault_mnr_race_winrm_password }}'
        'configured'
      no_log: true

    - name: Show service status
      ansible.windows.win_shell: "& '{{ acevo.nssm }}' status {{ acevo.service_name }}"
      register: svc_status
    - debug: var=svc_status.stdout_lines
```

> Note: the service runs as `MNR-RACE\MNR`; `vault_mnr_race_winrm_password` is that account's password (already in the vault). `no_log: true` keeps it out of Ansible output.

- [ ] **Step 4: Dry-run then apply**

Run: `cd ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible-playbook deploy-acevo-service.yml --check`
Expected: no errors (note: the `win_shell` nssm task may show as changed/skipped under check — acceptable).
Run without `--check` to apply. Expected recap: `failed=0`.

- [ ] **Step 5: Verify the service is registered (do NOT start yet — no blobs deployed)**

Run: `cd ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible windows -m win_shell -a "& 'C:\palace\tools\nssm.exe' status acevo-server"`
Expected: `SERVICE_STOPPED` (it will start once Task 8 deploys blobs).

- [ ] **Step 6: Commit**

```bash
git add scripts/acevo-season/server/run-acevo.ps1 ansible/deploy-acevo-service.yml ansible/group_vars/all/vars.yml
git commit -m "feat(acevo): NSSM service + wrapper + service deploy playbook"
```

---

### Task 8: Rotate script + rotation task + season deploy playbook

**Gated on Task 6 = PASS.**

**Files:**
- Create: `scripts/acevo-season/server/rotate.ps1`
- Create: `ansible/deploy-acevo-season.yml`

- [ ] **Step 1: Write `rotate.ps1`**

```powershell
# scripts/acevo-season/server/rotate.ps1
# Daily (05:00). Picks the active round from manifest.json (soonest date >= today,
# else the last), swaps it into seasondefinition.blob, and restarts the service
# ONLY if the blob changed. Never restarts into an undecodable blob.
$ErrorActionPreference = 'Stop'
$auto = 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest\automation'
$log  = Join-Path $auto 'rotate.log'
function L($m) { "$(Get-Date -Format o) $m" | Out-File -Append $log -Encoding utf8 }

try {
    $manifest = Get-Content (Join-Path $auto 'manifest.json') -Raw | ConvertFrom-Json
    $today = (Get-Date).Date
    $sorted = $manifest | Sort-Object { [datetime]::ParseExact($_.date, 'yyyy-MM-dd', $null) }
    $upcoming = $sorted | Where-Object { [datetime]::ParseExact($_.date, 'yyyy-MM-dd', $null) -ge $today }
    $active = if ($upcoming) { $upcoming[0] } else { $sorted[-1] }
    L "active round $($active.round) ($($active.date)) -> $($active.blob)"

    $src  = Join-Path $auto $active.blob
    $dst  = Join-Path $auto 'seasondefinition.blob'

    # sanity: the source blob must base64/zlib-decode
    $raw = [Convert]::FromBase64String((Get-Content $src -Raw).Trim())
    if ($raw.Length -lt 5) { throw "round blob too short" }

    $changed = -not (Test-Path $dst) -or `
               ((Get-FileHash $src).Hash -ne (Get-FileHash $dst).Hash)
    if (-not $changed) { L "no change; not restarting"; return }

    Copy-Item -LiteralPath $src -Destination $dst -Force
    L "swapped in $($active.blob); restarting service"
    Restart-Service acevo-server
    L "restarted"
} catch {
    L "ERROR: $_  (leaving running server untouched)"
    exit 1
}
```

- [ ] **Step 2: Write `deploy-acevo-season.yml`**

```yaml
# ansible/deploy-acevo-season.yml
# Usage: ansible-playbook deploy-acevo-season.yml -e season=q3
#   Requires ACEVO_*_PASSWORD in env OR pulls from vault (below).
- name: Deploy an AC EVO season
  hosts: windows
  gather_facts: false
  vars:
    auto: "{{ acevo.automation_dir }}"
    season_file: "../scripts/acevo-season/seasons/{{ season }}.yml"
    local_out: "/tmp/acevo-out-{{ season }}"
  tasks:
    - name: Generate blobs locally from the season file
      delegate_to: localhost
      environment:
        ACEVO_DRIVER_PASSWORD: "{{ vault_acevo_driver_password }}"
        ACEVO_ADMIN_PASSWORD: "{{ vault_acevo_admin_password }}"
        ACEVO_SPECTATOR_PASSWORD: "{{ vault_acevo_spectator_password }}"
      ansible.builtin.command:
        argv:
          - python3
          - ../scripts/acevo-season/gen.py
          - --season
          - "{{ season_file }}"
          - --templates
          - ../scripts/acevo-season/templates
          - --out
          - "{{ local_out }}"
      no_log: true

    - name: Ensure automation dir
      ansible.windows.win_file: { path: "{{ auto }}", state: directory }

    - name: Back up current blobs
      ansible.windows.win_shell: |
        $s = Get-Date -Format 'yyyyMMdd-HHmmss'
        Get-ChildItem '{{ auto }}\*.blob' -EA SilentlyContinue |
          ForEach-Object { Copy-Item $_.FullName "$($_.FullName).bak-$s" -Force }
        'backed up'

    - name: Push generated blobs + manifest
      ansible.windows.win_copy:
        src: "{{ local_out }}/"
        dest: "{{ auto }}\\"
      no_log: true

    - name: Push rotate.ps1
      ansible.windows.win_copy:
        src: ../scripts/acevo-season/server/rotate.ps1
        dest: "{{ auto }}\\rotate.ps1"

    - name: Register the daily rotation task (05:00)
      ansible.windows.win_shell: |
        schtasks /Create /TN AcevoRoundRotate /F /SC DAILY /ST 05:00 /RL HIGHEST /RU '{{ acevo.run_as }}' /RP '{{ vault_mnr_race_winrm_password }}' `
          /TR 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{{ auto }}\rotate.ps1"' | Out-Null
        'task registered'
      no_log: true

    - name: Apply the active round now (rotate + start/restart)
      ansible.windows.win_shell: |
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File '{{ auto }}\rotate.ps1' | Out-Null
        if ((Get-Service acevo-server).Status -ne 'Running') { Start-Service acevo-server }
        Start-Sleep 15
        (Get-Service acevo-server).Status

    - name: Clean up local generated blobs (contain plaintext passwords)
      delegate_to: localhost
      ansible.builtin.file: { path: "{{ local_out }}", state: absent }
```

- [ ] **Step 3: Deploy the example season**

Run: `cd ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible-playbook deploy-acevo-season.yml -e season=example`
Expected recap: `failed=0`; final task prints `Running`.

- [ ] **Step 4: Verify end to end**

Run: `cd ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible windows -m win_shell -a "Get-Service acevo-server | Select Status; Get-Content 'C:\Users\MNR\Desktop\mnr\ACEvo_Latest\automation\rotate.log' -Tail 5"`
Expected: `Running`; log shows the active round chosen and either "swapped in …; restarting" or "no change".
Confirm the game server registered to the lobby (tail the server log as in Task 6 Step 4).

- [ ] **Step 5: Verify clean stop leaves no orphan**

Run: `cd ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible windows -m win_shell -a "Stop-Service acevo-server; Start-Sleep 5; Get-Process AssettoCorsaEVOServer -EA SilentlyContinue | Select Id; Start-Service acevo-server"`
Expected: **no** `AssettoCorsaEVOServer` process id printed after stop (NSSM killed the tree via `AppStopMethodConsole`). If an orphan remains, raise `AppStopMethodConsole` / add `AppStopMethodWindow` in Task 7's nssm config and re-run.

- [ ] **Step 6: Commit**

```bash
git add scripts/acevo-season/server/rotate.ps1 ansible/deploy-acevo-season.yml
git commit -m "feat(acevo): rotate.ps1 + daily rotation task + season deploy playbook"
```

---

### Task 9: Docs + README + real season

**Files:**
- Create: `scripts/acevo-season/README.md`
- Modify: `docs/acevo-server.md`
- Modify: `CLAUDE.md`
- Create: `scripts/acevo-season/seasons/<real-season>.yml` (the actual upcoming calendar)

- [ ] **Step 1: Write `scripts/acevo-season/README.md`**

Cover: the wire format (point at `codec.py`), the season file keys (point at `seasons/example.yml` and `FIELD_MAP.md`), the "transform live templates, don't generate from scratch" rule, the `gen.py` CLI, how the service + daily rotation work, and the two playbooks. Mirror the tone/structure of `scripts/acc-championship/README.md`.

- [ ] **Step 2: Update `docs/acevo-server.md`**

Add a "Season automation" section: the server now runs as the `acevo-server` NSSM service (auto-start, crash-restart) driven by `run-acevo.ps1`; config comes from `automation\*.blob`; `AcevoRoundRotate` swaps the active round daily at 05:00; `Get-Service acevo-server` / `Get-Process AssettoCorsaEVOServer` are the up-checks. Update the "How it starts — by hand" section to note the service is now the primary path (GUI still usable for ad-hoc, same blob format). Note the Steam-update procedure now stops the **service** instead of the launcher.

- [ ] **Step 3: Update `CLAUDE.md`**

In the AC EVO section, add: config is now automated via `scripts/acevo-season/` (season.yml → blobs), deployed with `deploy-acevo-service.yml` (one-time) + `deploy-acevo-season.yml` (per season), and rotated weekly by `AcevoRoundRotate`. Note the passwords now live in `vault_acevo_*_password` and generated `*.blob` files are gitignored.

- [ ] **Step 4: Create the real season file**

Copy `seasons/example.yml` to the real season name and fill in the actual calendar (tracks, dates, weather). Validate: `cd scripts/acevo-season && python3 -c "import season; season.load_season('seasons/<real>.yml')"` — no exception.

- [ ] **Step 5: Commit**

```bash
git add scripts/acevo-season/README.md docs/acevo-server.md CLAUDE.md scripts/acevo-season/seasons/
git commit -m "docs(acevo): season-automation README + server/CLAUDE docs + real season"
```

---

## Notes / deviations from the spec

- **Round-trip test is semantic, not byte-identical** (see Global Constraints). The spec's "byte-identical" wording is superseded — the server only needs our blob to decode to the right JSON, and matching the GUI's .NET JSON + zlib output byte-for-byte is neither feasible nor necessary.
- **Task 4 was revised after the Task 2 capture (2026-07-27).** The real schema is deeply nested and per-session (`event_map.<eid>.session_map.<sid>`), durations are milliseconds, cars are objects (`allowed_cars_list_full`), and there are four port fields. Task 4's paths bind from `FIELD_MAP.md` and the golden tests run against the real committed template (not synthetic).
- **Weather is best-effort (user decision, 2026-07-27).** The single captured sample is clear-weather, so ambient/rain/randomness fields and the track's on-disk **path** encoding for *other* tracks are extrapolations. They are wired to the best-guess FIELD_MAP paths and **validated at the Task 6 spike** (which launches a different track, silverstone, so it exercises the track-path extrapolation). `weather_type` enum is left unchanged (rain enum string unknown). Task 4 reports these as DONE_WITH_CONCERNS.
- **Task 6 is a hard gate.** If the exe can't run headless without the GUI, Tasks 7–8 change to a config-gen-only deliverable (generate blobs + a launch `.bat`, human runs the GUI/command). Everything in Tasks 1–5 stays valid either way.

---

## Execution status — PAUSED 2026-07-27

Executed with subagent-driven-development on branch `feat/acevo-season-automation`.

**Done — the offline toolkit (Tasks 1–5), all reviewed, 16 tests passing:**

| Task | Commit(s) | Delivered |
|---|---|---|
| 1 Codec | `1d406bb` | `scripts/acevo-season/codec.py` (encode/decode); decoder CLI refactored onto it |
| 2 Capture | `e7968be`, `10aa256` | Secret-free `templates/{serverconfig,seasondefinition}.template.json`, `FIELD_MAP.md` (real nested paths + documented ambiguities), decode fixture, `vault_acevo_*_password` in the vault |
| 3 Season model | `d0226c7` | `season.py` (`load_season`, `active_round`), `seasons/example.yml` |
| 4 Transform | `ebd868e`, fix `fc55508` | `transform.py` — real per-session nested schema, ms durations, car-objects, four ports, best-effort weather, complete track-slug replacement (incl. `scene.containers[]`) |
| 5 gen.py | `69539fb` | `gen.py` CLI (season → `serverconfig.blob` + `round-NN.blob` + `manifest.json`); generated `*.blob` gitignored |

**Not done — deferred to a future OFF-PEAK session (NOT a Monday race window):**
- **Task 6 — validation spike (HARD GATE).** Direct-launch `AssettoCorsaEVOServer.exe` with a generated blob pair, GUI bypassed; confirm it boots, binds 34597, registers to the Kunos lobby, accepts passwords. Paused because 2026-07-27 was a Monday race evening and starting/stopping a server instance could collide with a live race. **Tasks 7–8 are gated on this passing.**
- **Task 7 — NSSM service + wrapper + `deploy-acevo-service.yml`.**
- **Task 8 — `rotate.ps1` + `AcevoRoundRotate` (05:00) + `deploy-acevo-season.yml`.**
- **Task 9 — docs (`acevo-server.md`, `CLAUDE.md`) + real season file.**

**Concerns carried forward to the Task 6 spike (must validate against a real second track / dynamic-weather sample):**
- Track-slug derivation is `name.lower()` from a single sample (Kyalami). Breaks for multi-word/punctuated tracks (e.g. `Spa-Francorchamps`, `Watkins Glen`) — needs a slug override map, confirmed against a real generated track load.
- Weather is **best-effort** (user decision): `mean_ambient_temperature_c`, `cloud_coverage`, `precipitation` + `initial_global_wetness`, `is_dynamic_weather`. Left unchanged: `weather_type` enum (rain string unknown) and the `initial_grip` enum (only numeric grip set). All extrapolated from one clear-weather snapshot.

**Minor findings logged for the eventual final review:** `codec.decode` raises `struct.error` (not `ValueError`) on a <4-byte blob; `season.active_round` parses each date twice; an unquoted-date YAML scalar would raise `TypeError` not `SeasonError`; `gen.py --out` isn't `required=True`.

**To resume:** bring the VPN up at an off-peak, non-Monday-race time; start at Task 6 in this plan. If the spike PASSES → Tasks 7→8→9. If it FAILS (exe needs the GUI) → fall back to the config-gen-only deliverable noted above. The final whole-branch review + merge of Tasks 1–5 is still pending (branch not yet merged).
