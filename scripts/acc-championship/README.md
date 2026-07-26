# ACC Server Manager championship tools

Configure ACC Server Manager championships — points, calendar, per-round track and weather —
from a `season.yml`, instead of clicking through the web UI round by round.

Targets the manager on `mnr-race` that serves `acc.mondaynightracing.co.za` (v1.4.6, JSON store
at `C:\Users\MNR\Desktop\mnr\Official Race Servers\Race\store.json`).

## The data model (this is what actually matters)

A championship is **two linked object types** in the JSON store:

| Store folder | Object | Holds |
|---|---|---|
| `championships/<id>.json` | Championship | Name, **Points** table, EntryList, and `Events[]` — each Event has an **ID** and a set of **Sessions** (Practice/Qualifying/Race). **No track, no weather.** |
| `presets/<id>.json` | Preset (one per round) | `Data.RaceConfig` — the **track**, **weather**, per-session timing. |

The join — **verified against the live manager**, after three wrong guesses:

- **`event.ID == preset.ID`** — each event is configured by the preset whose file/`ID` equals
  the event's ID. This is the join, *not* the session UUIDs.
- **`metaData = "championship:<champID>:<eventID>"`** in the preset's `RaceConfig`.
- The **3 session UUIDs (FP/Q/R) are a shared template** reused across every event and preset in
  the championship — they are *not* a per-event key.
- Non-deleted objects must carry `"Deleted": "0001-01-01T00:00:00Z"` (the zero-time string). A
  `null` makes the manager's Go `time.Time` skip the object.

Get any of these wrong and the manager silently renders **"0 events configured"** even though the
events are sitting in the championship file (which is why its name/points still show).

## Two tools

### `remap.py` — update an existing championship (VERIFIED, use this)

Rewrites the schedule of a championship the manager already has, transforming its own files in
place: **keeps every event ID, preset ID, and metaData**, changes only track / weather / time /
race-length. Because the manager already recognises those IDs, the events keep rendering.

```bash
python3 remap.py \
  --championship orig/championships/<id>.json \
  --presets-dir  orig/presets \
  --season       seasons/q2a.yml \
  --out          ./out
```

Feed it the championship + presets **as the manager wrote them** (pull them from the live store or
a `.backups/…` folder). It normalises each event to the season's FP/Q/R and applies the calendar.

### `gen.py` — create a brand-new championship (UNVERIFIED)

Emits a new championship + presets from a `season.yml` using the correct model (`event.ID ==
preset.ID`, shared session template). **Not confirmed to render from a raw file-drop** — the
manager may require a championship to be created through the UI first. Safest path for a new
season: make an empty championship in the UI, export/note its ID, then `remap.py` onto it.

## Season file

See `season.example.yml`. `seasons/q2a.yml` / `q2b.yml` are the live Q2 2026 calendar. Keys:
`championship.id` (update-in-place target), `championship.preset_name` (the per-round event name),
`points.places`, `session_defaults` (FP/Q/R minutes + day-of-weekend), `weather_defaults`, and
`rounds[]` with `track`, `hour_of_day` (applied to all sessions), `race_minutes`, and optional
per-round `weather`.

## Deploy

`ansible/deploy-acc-championships.yml` stops the `acc-server-manager` **service**, backs up the
championships + their linked presets, replaces them, restarts the service, and verifies. The
manager reads its store only at startup, so the restart is required; it briefly blips the live
ACC servers, so run off-peak.

```bash
# stage a merged dir with championships/ and presets/ (from remap.py output), then:
ansible-playbook deploy-acc-championships.yml -e stage_dir=/path/to/staged
```

`templates/` holds envelope objects captured from the live store (secret-free) that `gen.py`
patches; `remap.py` needs no templates (it edits real files).
