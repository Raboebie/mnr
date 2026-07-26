#!/usr/bin/env python3
"""Remap an EXISTING ACC Server Manager championship onto a new schedule, in place.

The manager's real data model (learned the hard way):

  * A championship's Events each have an ID. The preset that configures an event is the one
    whose FILE ID / preset.ID EQUALS the event's ID  ->  event.ID == preset.ID is the join.
  * metaData = "championship:<champID>:<eventID>"  (same eventID == presetID).
  * The 3 session UUIDs (FP/Q/R) are a SHARED template reused across every event and preset in
    the championship -- they are NOT a per-event key.

A file-drop with fresh UUIDs therefore shows "0 events configured" because no preset resolves to
an event. So we do not synthesise: we take the championship + its presets exactly as the manager
wrote them and rewrite only the per-round race content, preserving every event.ID / preset.ID /
metaData and reusing the shared session UUIDs. Two of the original events are quirky 1-session
(race-only) events; we normalise every event to the standard FP/Q/R from the season file.

Usage:
    remap.py --championship orig/championships/<id>.json --presets-dir orig/presets \\
             --season seasons/q2a.yml --out out/
"""
import argparse, copy, json, os, sys
from datetime import datetime, timezone

NS_PER_MIN = 60 * 1_000_000_000
ZERO_TIME = "0001-01-01T00:00:00Z"
# season key, ACC sessionType, champ Session.Type int, champ Session.Name
SPEC = [("practice", "FP", 0, "Practice"), ("qualifying", "Q", 1, "Qualifying"), ("race", "R", 2, "Race")]


def load(p):
    with open(p, encoding="utf-8") as f:
        return __import__("yaml").safe_load(f) if p.endswith((".yml", ".yaml")) else json.load(f)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


def shared_session_uuids(presets):
    """The FP/Q/R session UUIDs are shared across the championship; pull them from any preset
    that has all three."""
    for p in presets.values():
        sess = {s["sessionType"]: s["sessionID"] for s in p["Data"]["RaceConfig"]["sessions"]}
        if all(t in sess for t in ("FP", "Q", "R")):
            return sess
    sys.exit("no preset with a full FP/Q/R session set to source the shared session UUIDs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--championship", required=True)
    ap.add_argument("--presets-dir", required=True)
    ap.add_argument("--season", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    champ = load(a.championship)
    season = load(a.season)
    rounds = season["rounds"]
    sdef = season.get("session_defaults", {})
    wdef = season.get("weather_defaults", {})
    cid = champ["ID"]
    now = now_iso()

    if len(champ["Events"]) != len(rounds):
        sys.exit(f"{champ['Name']}: {len(champ['Events'])} events but {len(rounds)} rounds; must match")

    # presets linked to this championship, indexed by their ID (== the event ID they configure)
    presets = {}
    for fn in os.listdir(a.presets_dir):
        if not fn.endswith(".json"):
            continue
        p = load(os.path.join(a.presets_dir, fn))
        if p.get("ChampionshipID") == cid:
            presets[p["ID"]] = p
    sess_uuid = shared_session_uuids(presets)

    champ["Description"] = season.get("championship", {}).get("description", champ.get("Description", ""))
    champ["Updated"] = now
    out_presets = []

    for i, (event, rnd) in enumerate(zip(champ["Events"], rounds), 1):
        preset = presets.get(event["ID"])
        if preset is None:
            sys.exit(f"round {i}: no preset with ID == event.ID {event['ID']}")
        preset = copy.deepcopy(preset)
        pname = season.get("championship", {}).get("preset_name")
        if pname:
            preset["Name"] = pname

        hour = rnd.get("hour_of_day")
        champ_sessions, preset_sessions = [], []
        for key, stype, tint, sname in SPEC:
            cfg = dict(sdef.get(key, {}))
            minutes = int(rnd["race_minutes"]) if (key == "race" and "race_minutes" in rnd) else int(cfg.get("minutes", 0))
            sid = sess_uuid[stype]
            champ_sessions.append({"ID": sid, "Type": tint, "Index": 0, "Name": sname, "IsTimed": True,
                                   "Duration": minutes * NS_PER_MIN, "NumLaps": 0, "Results": None,
                                   "CompletedTime": ZERO_TIME})
            preset_sessions.append({"hourOfDay": hour if hour is not None else cfg.get("hour_of_day", 12),
                                    "dayOfWeekend": cfg.get("day_of_weekend", tint + 1),
                                    "timeMultiplier": cfg.get("time_multiplier", 1),
                                    "sessionType": stype, "sessionDurationMinutes": minutes, "sessionID": sid})
        event["Sessions"] = champ_sessions

        rc = preset["Data"]["RaceConfig"]
        rc["track"] = rnd["track"]
        rc["sessions"] = preset_sessions
        weather = dict(wdef); weather.update(rnd.get("weather", {}) or {})
        for wk, rk in [("ambient_temp", "ambientTemp"), ("track_temp", "trackTemp"), ("cloud_level", "cloudLevel"),
                       ("rain", "rain"), ("weather_randomness", "weatherRandomness")]:
            if wk in weather:
                rc[rk] = weather[wk]
        preset["Updated"] = now
        out_presets.append(preset)

    cdir = os.path.join(a.out, "championships"); pdir = os.path.join(a.out, "presets")
    os.makedirs(cdir, exist_ok=True); os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(cdir, f"{cid}.json"), "w", encoding="utf-8") as f:
        json.dump(champ, f, indent=2)
    for p in out_presets:
        with open(os.path.join(pdir, f"{p['ID']}.json"), "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2)

    print(f"{champ['Name']} ({cid}): remapped {len(out_presets)} rounds (event.ID==preset.ID preserved)")
    for i, (event, rnd, p) in enumerate(zip(champ["Events"], rounds, out_presets), 1):
        rc = p["Data"]["RaceConfig"]
        r = next(s for s in rc["sessions"] if s["sessionType"] == "R")
        print(f"  R{i} evt={event['ID'][:8]} {rc['track']:<15} hour={r['hourOfDay']:>2} "
              f"race={r['sessionDurationMinutes']}m rain={rc['rain']} cloud={rc['cloudLevel']}")


if __name__ == "__main__":
    main()
