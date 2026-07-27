# AC EVO season automation + service — design

**Date:** 2026-07-27
**Status:** Approved design, ready for implementation plan
**Target:** The AC EVO dedicated server on `mnr-race` (`10.104.0.10`). See
[`docs/acevo-server.md`](../../acevo-server.md).

## Goal

Bring the AC EVO server up to the automation level the ACC Server Manager now has: define a
**whole season upfront** as config-as-code, have the **correct round applied automatically each
week**, and run the server as a **managed Windows service** (auto-start on boot, crash-restart) so
the "someone must RDP in and start it before a Monday" risk disappears.

Today AC EVO is hand-started via the `.NET ServerLauncher` GUI, and its entire config is packed
into two base64→zlib→JSON blobs on the `AssettoCorsaEVOServer.exe` command line:

```
AssettoCorsaEVOServer.exe -serverconfig <blob> -seasondefinition <blob>
```

Each blob is `base64( 4-byte big-endian uncompressed length + zlib.deflate(JSON) )`.
`scripts/acevo-decode-launch.py` already decodes them; there is no encoder and no automation.

## Approach (chosen: "B")

Front-end: a `scripts/acevo-season/` toolkit (mirroring `scripts/acc-championship/`) — a
`season.yml` calendar plus a `gen.py` that transforms captured **live** config templates and a
codec that round-trips the blobs. All blob **generation** happens on the workstation (Python); the
server just swaps files and restarts.

Runtime: an NSSM service runs a tiny wrapper that reads two blob **files** and execs the game
server directly (GUI bypassed, because a GUI can't run headless as a service). A config change is
"rewrite the `seasondefinition` file + `Restart-Service`." A daily off-peak scheduled task picks
the active round by date and restarts **only if the round changed**.

This mirrors two patterns already in the repo:
- **Palace** — NSSM → `node server.js`, config in files (here: NSSM → wrapper → exe, config in
  blob files).
- **ACC championships** — generate on the workstation, deploy files, the box stays "dumb" and just
  swaps + restarts.

Rejected alternatives:
- **A — blobs baked into the NSSM service args.** Every config change reconfigures the service;
  multi-KB command-line args. More coupling for no benefit.
- **C — scheduled per-night relaunch, no persistent service.** Discards the "stays up for weeks"
  behaviour and adds start/stop-timing fragility.

## Components

### `scripts/acevo-season/` (workstation)

| File | Purpose |
|---|---|
| `codec.py` | `encode(obj) -> blob` and `decode(blob) -> obj` for the base64/len-prefix/zlib format. Single source of truth for the wire format. |
| `gen.py` | `season.yml` + captured templates + passwords → `serverconfig.blob`, one `seasondefinition` blob **per round** (`round-01.blob` …), and `manifest.json` (date → round map). |
| `seasons/<name>.yml` | The season calendar (see **Season file** below). |
| `templates/serverconfig.template.json` | Captured from the live decoded `-serverconfig`, **secret-free** (passwords → placeholders). |
| `templates/seasondefinition.template.json` | Captured from the live decoded `-seasondefinition`. |
| `README.md` | Usage, the wire format, and the "transform live templates, don't generate from scratch" rule. |

`acevo-decode-launch.py` is refactored to import `codec.decode` (keep its CLI/UX; remove the
duplicated format code).

**Transform, don't synthesize.** `gen.py` starts from the captured live template JSON and
overrides only the fields it models, preserving everything else verbatim (e.g. the `tuning_type`
field the GUI adds per run). This is the direct analogue of the ACC lesson that a from-scratch
object silently fails — we only touch known fields on a known-good baseline.

**Modeled fields:**
- `serverconfig`: server name, `server_tcp_listener_port` / `server_tcp_internal_port` (both
  34597 today), HTTP port (8080), max players (19), allowed-cars list, results path, and the
  driver / admin / spectator **passwords** (injected from vault).
- `seasondefinition` (per round): track, layout, session set (practice/qualify/race) with
  durations, `hour_of_day` / time-of-day, weather (temps, cloud, rain, randomness), initial grip.

### Server-side, under `C:\Users\MNR\Desktop\mnr\ACEvo_Latest\automation\`

| File | Purpose |
|---|---|
| `serverconfig.blob` | The live server-config blob (static across a season). |
| `seasondefinition.blob` | The **active** round's blob. `rotate.ps1` overwrites this. |
| `round-01.blob` … | All precomputed per-round season blobs, pushed at deploy. |
| `manifest.json` | `[{round: 1, date: "YYYY-MM-DD", blob: "round-01.blob"}, …]` |
| `run-acevo.ps1` | NSSM wrapper: read the two live blob files, exec `AssettoCorsaEVOServer.exe -serverconfig <blob> -seasondefinition <blob>`, exit when the exe exits. |
| `rotate.ps1` | Daily: pick active round from `manifest.json`, copy its blob over `seasondefinition.blob`, restart the service **only if it changed**. Pure PowerShell — no Python on the box. |
| `rotate.log` | Rotation log. |

**Service `acevo-server`** — NSSM, `Start=SERVICE_AUTO_START`, `AppExit Default Restart`, runs as
`MNR-RACE\MNR`, `AppDirectory` = the install dir (so relative paths and `content.kspkg` resolve).
Runs `run-acevo.ps1`. `Get-Service acevo-server` / `Get-Process AssettoCorsaEVOServer` are the
up-checks.

**Scheduled task `AcevoRoundRotate`** — daily at **05:00 SAST**, runs `rotate.ps1`. In steady
state the active round flips once a week, so the service restarts **Tuesday ~05:00** (after
Monday's race, off track).

### Ansible

| Playbook | Role |
|---|---|
| `ansible/deploy-acevo-service.yml` | One-time-ish: install the NSSM `acevo-server` service, push `run-acevo.ps1` / `rotate.ps1`, register `AcevoRoundRotate`. Mirrors `deploy-acc-manager-service.yml`. |
| `ansible/deploy-acevo-season.yml` | Per-season: run `gen.py` locally (vault passwords injected), back up current blobs, push `serverconfig.blob` + all round blobs + `manifest.json`, run `rotate.ps1` once to apply the active round, restart, verify. Mirrors `deploy-acc-championships.yml`. |

## Season file (`seasons/<name>.yml`)

Mirrors `scripts/acc-championship/seasons/q2a.yml` where sensible:

```yaml
server:
  name: "MNR | Monday Night Racing"
  game_port: 34597           # listener + internal both set to this
  http_port: 8080
  max_players: 19
  cars: [...]                # allowed-cars list (or a ref); static for the season
  # passwords are NOT here — injected from vault at generate time

race_start_time: "18:00:00+02:00"   # informational; AC EVO has no real-world scheduler

session_defaults:
  practice:   {minutes: 240}
  qualifying: {minutes: 15}
  race:       {minutes: 30}

weather_defaults:
  ambient_temp: 24
  track_temp: 30
  cloud_level: 0.05
  rain: 0
  weather_randomness: 4

rounds:
  - {track: silverstone, layout: gp, hour_of_day: 21, race_minutes: 30, date: "2026-07-27"}
  - {track: spa,         layout: gp, hour_of_day: 17, race_minutes: 30, date: "2026-08-03"}
  # …
```

Exact track / layout / weather / grip key names are pinned during implementation against the
**captured live `seasondefinition`** (we adopt the game's own field names).

## Data flow

```
season.yml + templates + vault passwords
        │  gen.py (workstation)
        ▼
serverconfig.blob + round-NN.blob[] + manifest.json
        │  deploy-acevo-season.yml (WinRM)
        ▼
…\ACEvo_Latest\automation\   (blobs + manifest on the server)
        │  rotate.ps1 (applies active round)
        ▼
seasondefinition.blob  →  Restart-Service acevo-server  →  run-acevo.ps1  →  AssettoCorsaEVOServer.exe
        ▲
        │  AcevoRoundRotate (daily 05:00, restart only if round changed)
```

## Round selection

Active round = **the soonest round whose `date ≥ today`**. So round N is active from the day after
round N‑1's race until round N's own race day (inclusive), leaving the server correctly configured
all week. After the final round's date passes, the last round stays active (harmless — no restart).

The **authoritative** selection runs in `rotate.ps1` on the server (PowerShell, over the dates in
`manifest.json`) — it is the only place "today" is evaluated. The rule is trivial (pick the entry
with the smallest `date ≥ today`, else the last entry). `gen.py --active-round` implements the same
rule for local preview/cross-check, and `rotate.ps1` **logs the chosen round on every run** so the
selection is auditable. Date-boundary cases (before season start, race day, day-after, after final
round) are covered by unit tests against the `gen.py` implementation.

## Error handling & secrets

- **`rotate.ps1`**: validate the target blob decodes (length-prefix + zlib sanity) *before*
  swapping; on any error, log and leave the running server untouched — never restart into a bad
  config. (Same discipline as the cert-renewal `httpd -t` guard.)
- **`gen.py`**: fail loudly on an unknown track/layout or a missing template field; never emit a
  blob that does not round-trip through `codec`.
- **Service**: NSSM crash-restart with throttle so a fast-failing exe doesn't hot-loop.
- **Secrets**: templates are secret-free; passwords are injected only at generate time from
  `vault_acevo_driver_password` / `vault_acevo_admin_password` / `vault_acevo_spectator_password`.
  Generated blobs contain **plaintext** passwords (as the live config does today), so they live
  only on the server and are **gitignored** on the workstation — never committed. `.gitignore`
  gets `scripts/acevo-season/**/*.blob` (and any generated `out/`).

## Testing

- **Codec round-trip (de-risking, first):** `decode(live blob) → encode → byte-identical`. Proves
  the wire format is exactly reproducible before anything depends on it.
- **`gen.py` golden tests:** a `season.yml` round → the `seasondefinition` blob decodes to the
  expected track/layout/time/weather/duration; `serverconfig` decodes to the expected settings with
  injected passwords.
- **Round-selection unit tests:** date → active round across the season boundaries (before start,
  race day, day-after, after final).
- **Validation spike / go-no-go gate (server, task #1):** manually direct-launch
  `AssettoCorsaEVOServer.exe` with a generated blob pair (GUI bypassed) and confirm it boots, binds
  34597, registers to the Kunos lobby websocket, and accepts the passwords. Only after this passes
  do we build the service. If the exe cannot run headless without the GUI, fall back to "automate
  config generation, keep manual launch."

## Risks

| Risk | Mitigation |
|---|---|
| The game server may not run headless / as a service without the GUI launcher. | The validation spike gates all service work. Fallback: config-gen only, manual launch. |
| Blob JSON schema drifts between game versions (e.g. new `tuning_type`-style fields). | Transform captured live templates (preserve unknown fields); re-capture templates after a Steam update. |
| Auto-restart interrupts a live session. | Restart only on round change, at 05:00 (off track); `rotate.ps1` checks `Get-Process` and logs. |
| Passwords leak via committed blobs. | Blobs gitignored; templates secret-free; passwords from vault only. |

## Out of scope

- Automating the **Steam update** procedure (still the manual hash-compare push in
  `docs/acevo-server.md`) — the service just changes *stop the launcher* to *stop the service*.
- Per-round car/entry rotation (season keeps a static car list; a per-round `cars` override can be
  added later if wanted).
- A web UI. AC EVO has no server manager; this is file/CLI + Ansible, matching the rest of the repo.

## Rollout order (informs the implementation plan)

1. `codec.py` + round-trip test (offline, safe).
2. Capture the live blobs → secret-free templates (server, read-only).
3. `gen.py` + season model + golden/date tests (offline).
4. **Validation spike:** direct-launch on the server (go/no-go).
5. NSSM service + `run-acevo.ps1` + `deploy-acevo-service.yml`.
6. `rotate.ps1` + `AcevoRoundRotate` + `deploy-acevo-season.yml`.
7. Docs: update `docs/acevo-server.md` and `CLAUDE.md`.
