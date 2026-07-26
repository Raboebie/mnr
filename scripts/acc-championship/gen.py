#!/usr/bin/env python3
"""Generate a NEW ACC Server Manager championship + per-round preset JSON from a season file.

    >>> To UPDATE an EXISTING championship (e.g. reschedule a season), use remap.py instead. <<<
    remap.py transforms the manager's own files in place and is the VERIFIED path. Creating a
    brand-new championship purely by dropping files into the store (what this tool does) is NOT
    verified against a running manager -- it may need the championship to be created through the
    UI first. Prefer: make an empty championship in the UI, then remap.py onto it.

The ACC Server Manager (v1.4.x, on `mnr-race` serving acc.mondaynightracing.co.za) stores a
championship as TWO linked object types in its JSON store (store.json/):

    championships/<champID>.json   Name, Points table, EntryList, and Events[]. Each Event has
                                   an ID and a set of Sessions (Practice/Qualifying/Race), but
                                   NO track and NO weather.

    presets/<eventID>.json         One per round -- Data.RaceConfig carries the track + weather.

The join (learned the hard way -- see docs/acc-server-manager.md):
  * event.ID == preset.ID  -- each event is configured by the preset with the SAME id.
  * metaData = "championship:<champID>:<eventID>".
  * The 3 session UUIDs (FP/Q/R) are a SHARED template reused across every event and preset in
    the championship, NOT a per-event key.
Get any of these wrong and the manager silently shows "0 events configured". Session duration is
written to both the championship Event (nanoseconds) and the preset (minutes) from one source so
they cannot drift.

Deploy (the manager reads its store at startup): use ansible/deploy-acc-championships.yml, which
stops the service, swaps the files, and leaves it for a restart. See README.md.

Usage:
    gen.py --season season.yml --out ./out
"""

import argparse
import copy
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# ACC session type -> (championship Session.Type int, championship Session.Name, season key)
SESSION_SPEC = [
    ("FP", 0, "Practice", "practice"),
    ("Q", 1, "Qualifying", "qualifying"),
    ("R", 2, "Race", "race"),
]
ZERO_TIME = "0001-01-01T00:00:00Z"
NS_PER_MINUTE = 60 * 1_000_000_000


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def new_uuid() -> str:
    return str(uuid.uuid4())


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        if path.endswith((".yml", ".yaml")):
            import yaml  # deferred so JSON-only users need no PyYAML
            return yaml.safe_load(fh)
        return json.load(fh)


def merge(base: dict, override) -> dict:
    """Shallow-merge an override dict onto a copy of base. override may be None."""
    out = dict(base or {})
    if override:
        out.update(override)
    return out


def build(season: dict, champ_tpl: dict, preset_tpl: dict):
    c = season.get("championship", {})
    champ = copy.deepcopy(champ_tpl)
    # championship.id present => update an existing championship in place (keep its ID/URL);
    # absent => a fresh championship.
    champ_id = c.get("id") or new_uuid()
    now = now_iso()
    champ["ID"] = champ_id
    champ["Name"] = c.get("name", "Unnamed Championship")
    champ["Description"] = c.get("description", "")
    champ["DefaultTab"] = c.get("default_tab", "")
    champ["IgnoreXWorstEvents"] = c.get("ignore_x_worst_events", 0)
    champ["Created"] = now
    champ["Updated"] = now
    # Manager writes non-deleted objects with the zero-time STRING, not null. A null here makes
    # its Go time.Time parse skip the object, and the championship shows "0 events configured".
    champ["Deleted"] = ZERO_TIME

    # Points: keep template's structural fields (MultiClass, ClassType, ...), override the knobs.
    pts_in = season.get("points", {})
    champ["Points"] = dict(champ_tpl.get("Points", {}))
    if "places" in pts_in:
        champ["Points"]["Places"] = [int(x) for x in pts_in["places"]]
    champ["Points"]["PolePosition"] = pts_in.get("pole_position", champ["Points"].get("PolePosition", 0))
    champ["Points"]["BestLap"] = pts_in.get("best_lap", champ["Points"].get("BestLap", 0))
    if "required_race_time_percentage" in pts_in:
        champ["Points"]["RequiredRaceTimePercentage"] = pts_in["required_race_time_percentage"]

    session_defaults = season.get("session_defaults", {})
    weather_defaults = season.get("weather_defaults", {})

    champ["Events"] = []
    presets = []

    rounds = season.get("rounds", [])
    if not rounds:
        raise SystemExit("season has no 'rounds'")

    # The 3 session UUIDs (FP/Q/R) are a SHARED template reused by every event and preset in the
    # championship -- NOT a per-event key. The manager depends on this.
    session_uuids = {stype: new_uuid() for stype, *_ in SESSION_SPEC}

    for idx, rnd in enumerate(rounds, 1):
        if "track" not in rnd:
            raise SystemExit(f"round {idx} is missing 'track'")

        # One ID per round, shared by the event AND its preset: event.ID == preset.ID is the join
        # the manager uses to bind a round's track/weather (preset) to its event.
        round_id = new_uuid()
        round_sessions = rnd.get("sessions", {})
        champ_sessions = []
        preset_sessions = []

        for stype, type_int, sname, key in SESSION_SPEC:
            default = session_defaults.get(key)
            override = round_sessions.get(key)
            # A session is included if either a default or a per-round config exists for it,
            # unless the round explicitly sets it to false/null to drop it.
            if key in round_sessions and override is None:
                continue
            cfg = merge(default, override)
            if not cfg:
                continue
            # round-level shorthands: hour_of_day/day_of_weekend apply to every session in the
            # round; race_minutes sets just the race duration (the common per-round knob).
            if "hour_of_day" in rnd:
                cfg["hour_of_day"] = rnd["hour_of_day"]
            if "day_of_weekend" in rnd:
                cfg["day_of_weekend"] = rnd["day_of_weekend"]
            if key == "race" and "race_minutes" in rnd:
                cfg["minutes"] = rnd["race_minutes"]
            minutes = int(cfg.get("minutes", 0))
            sid = session_uuids[stype]
            champ_sessions.append({
                "ID": sid,
                "Type": type_int,
                "Index": 0,
                "Name": sname,
                "IsTimed": True,
                "Duration": minutes * NS_PER_MINUTE,
                "NumLaps": 0,
                "Results": None,
                "CompletedTime": ZERO_TIME,
            })
            preset_sessions.append({
                "hourOfDay": cfg.get("hour_of_day", 12),
                "dayOfWeekend": cfg.get("day_of_weekend", type_int + 1),
                "timeMultiplier": cfg.get("time_multiplier", 1),
                "sessionType": stype,
                "sessionDurationMinutes": minutes,
                "sessionID": sid,
            })

        if not champ_sessions:
            raise SystemExit(f"round {idx} ({rnd['track']}) has no sessions")

        champ["Events"].append({
            "ID": round_id,
            "Created": now,
            "StartedTime": ZERO_TIME,
            "StartedOnServerID": 0,
            "CompletedTime": ZERO_TIME,
            "InverseGridRaceStarting": False,
            "Teams": {},
            "ChampionshipPointsMultiplier": rnd.get("points_multiplier", 1),
            "PointsPenalties": {},
            "Sessions": champ_sessions,
        })

        preset = copy.deepcopy(preset_tpl)
        preset_id = round_id  # preset.ID == event.ID is the join
        preset["ID"] = preset_id
        preset["Name"] = rnd.get("name", c.get("preset_name", champ["Name"]))
        preset["ChampionshipID"] = champ_id
        preset["ChampionshipName"] = champ["Name"]
        preset["IsPreChampionshipPractice"] = False
        preset["Created"] = now
        preset["Updated"] = now
        preset["Deleted"] = ZERO_TIME  # zero-time string, not null (see championship Deleted above)

        weather = merge(weather_defaults, rnd.get("weather"))
        rc = preset["Data"]["RaceConfig"]
        rc["track"] = rnd["track"]
        rc["metaData"] = f"championship:{champ_id}:{preset_id}"
        rc["sessions"] = preset_sessions
        if "ambient_temp" in weather:
            rc["ambientTemp"] = weather["ambient_temp"]
        if "track_temp" in weather:
            rc["trackTemp"] = weather["track_temp"]
        if "cloud_level" in weather:
            rc["cloudLevel"] = weather["cloud_level"]
        if "rain" in weather:
            rc["rain"] = weather["rain"]
        if "weather_randomness" in weather:
            rc["weatherRandomness"] = weather["weather_randomness"]
        if "fixed_condition_qualification" in weather:
            rc["isFixedConditionQualification"] = bool(weather["fixed_condition_qualification"])

        presets.append(preset)

    verify(champ, presets)
    return champ, presets


def verify(champ: dict, presets: list) -> None:
    """The join the manager actually uses: each event is configured by the preset whose ID equals
    the event's ID, with metaData 'championship:<champID>:<eventID>'."""
    if len(champ["Events"]) != len(presets):
        raise SystemExit(f"internal: {len(champ['Events'])} events vs {len(presets)} presets")
    for i, (event, preset) in enumerate(zip(champ["Events"], presets), 1):
        if event["ID"] != preset["ID"]:
            raise SystemExit(f"internal: round {i} event.ID != preset.ID")
        meta = preset["Data"]["RaceConfig"]["metaData"]
        if meta != f"championship:{champ['ID']}:{event['ID']}":
            raise SystemExit(f"internal: round {i} metaData wrong: {meta}")


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", required=True, help="season definition (.yml/.yaml/.json)")
    ap.add_argument("--templates-dir", default=os.path.join(here, "templates"),
                    help="dir with championship.template.json + preset.template.json")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "out"),
                    help="output dir (championships/ and presets/ are created under it)")
    ap.add_argument("--indent", type=int, default=2, help="JSON indent (0 = compact)")
    args = ap.parse_args()

    season = load(args.season)
    champ_tpl = load(os.path.join(args.templates_dir, "championship.template.json"))
    preset_tpl = load(os.path.join(args.templates_dir, "preset.template.json"))

    champ, presets = build(season, champ_tpl, preset_tpl)

    champ_dir = os.path.join(args.out, "championships")
    preset_dir = os.path.join(args.out, "presets")
    os.makedirs(champ_dir, exist_ok=True)
    os.makedirs(preset_dir, exist_ok=True)
    indent = args.indent or None

    champ_path = os.path.join(champ_dir, f"{champ['ID']}.json")
    with open(champ_path, "w", encoding="utf-8") as fh:
        json.dump(champ, fh, indent=indent)

    for preset in presets:
        with open(os.path.join(preset_dir, f"{preset['ID']}.json"), "w", encoding="utf-8") as fh:
            json.dump(preset, fh, indent=indent)

    print(f"championship  {champ['Name']!r}  ({champ['ID']})")
    print(f"  -> {champ_path}")
    print(f"  {len(champ['Events'])} rounds, {len(presets)} presets in {preset_dir}")
    for i, (event, preset) in enumerate(zip(champ["Events"], presets), 1):
        rc = preset["Data"]["RaceConfig"]
        durs = " ".join(f"{s['sessionType']}{s['sessionDurationMinutes']}" for s in rc["sessions"])
        print(f"  round {i:2d}: {rc['track']:<16} clouds={rc.get('cloudLevel')} rain={rc.get('rain')}  [{durs}]")
    print("\nDeploy: stop acc-server-manager, copy out/championships/* and out/presets/* into the\n"
          "store.json/ subfolders of the same name, then start it again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
