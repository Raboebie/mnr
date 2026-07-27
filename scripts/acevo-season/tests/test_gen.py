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
