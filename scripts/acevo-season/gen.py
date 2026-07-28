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

    if not args.out:
        ap.error("--out is required unless --active-round")

    tdir = Path(args.templates)
    sc_template = json.loads((tdir / "serverconfig.template.json").read_text())
    tracks = json.loads((HERE / "tracks.json").read_text())

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sc = build_serverconfig(sc_template, data["server"], _passwords_from_env())
    (out / "serverconfig.blob").write_text(encode(sc))

    manifest = []
    for i, r in enumerate(data["rounds"], 1):
        sd = build_seasondefinition(r, data["session_defaults"],
                                    data.get("weather_defaults", {}), tracks)
        name = f"round-{i:02d}.blob"
        (out / name).write_text(encode(sd))
        manifest.append({"round": i, "date": r["date"], "blob": name})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(manifest)} round blobs + serverconfig + manifest to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
