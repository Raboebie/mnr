# ACC Server Manager (acc.mondaynightracing.co.za)

The Assetto Corsa **Competizione** race platform for MNR — distinct from the AC **EVO**
server ([acevo-server.md](acevo-server.md)). It's the **Emperor Servers / JustaPenguin
"Assetto Corsa Competizione Server Manager"** (the install is now **v1.6.2** per `/healthcheck.json` — older notes say v1.4.6; it has been updated): a Go web app that manages several ACC
dedicated-server instances, runs championships, and stores results, all behind a web UI.

| | |
|---|---|
| Host | `mnr-race` (`10.104.0.10`) |
| Install dir | `C:\Users\MNR\Desktop\mnr\Official Race Servers\Race` |
| Web UI bind | `http://…:8773` on the box |
| Public URL | `https://acc.mondaynightracing.co.za` → Apache reverse-proxies `http://10.104.0.10:8773/` + WS upgrade (wildcard cert, see [mnr-server.md](mnr-server.md)) |
| Manager exe | `acc-server-manager.exe` (~43 MB) |
| ACC server exe | `accServer.exe` (the manager spawns copies of it) |
| Store | `store.json\` — a **JSON store** (one file per object), `store: path: store.json` in `config.yml` |
| License | `OSM.License` (this is a paid product) |

## How it starts

Runs as a Windows **service** (set up 2026-07-26): NSSM service **`acc-server-manager`**,
`Automatic` start (comes up on boot), crash-restart (`AppExit Default Restart`), running as
`MNR-RACE\MNR`, `AppDirectory` set to the install dir so it reads the right `store.json`. Logs at
`...\Race\logs\service-*.log`. Managed with `nssm.exe` (`C:\palace\tools\nssm.exe`) or plain
`Start-Service` / `Stop-Service acc-server-manager`. On start it auto-launches its configured ACC
servers.

> Before this it was hand-started from an RDP session, which meant every store change needed
> someone at the console to restart it. As a service it restarts over WinRM, so
> `deploy-acc-championships.yml` can stop → swap → start unattended. `config.yml` has
> `disable_windows_browser_open: true` so the headless service does not try to pop a browser.
> To revert to hand-start: `nssm remove acc-server-manager confirm`.

`Get-Service acc-server-manager` / `Get-Process accServer` are the up-checks (manager, then the
live race servers).

## The three ACC server instances

The manager runs up to three ACC dedicated servers, configured under `store.json\servers\`:

| Instance | Server name | Cars | Slots |
|---|---|---|---|
| `server_0` | Monday Night Racing - A | GT3 | 45 |
| `server_1` | Monday Night Racing - B | GT3 | 45 |
| `server_2` | Monday Night Racing - C | GT3 | 20 |

Base ports in each `serverOptions.json` are `tcpPort 9232 / udpPort 9231`, but the **manager
allocates the actual ports at launch** (it tracks the last-used ports in
`servers\server_N\meta\lastTCPPortUsed.json` / `lastUDPPortUsed.json`), so the live ports of a
running instance may differ from the stored base. All three register to the ACC lobby
(`registerToLobby 1`).

As of 2026-07-26 two `accServer.exe` were live (up since 2026-07-23), i.e. A and B were
hosting — the manager is not just an idle admin panel, it keeps race servers running.

## Config lives in the JSON store, not in ini files

Everything the UI configures is persisted as JSON under `store.json\`:

```
store.json\
  championships\   <uuid>.json   one per championship  (see data model below)
  presets\         <uuid>.json   saved event configs / per-round configs
  servers\         server_0..2\  per-instance ACC server options + meta
  accounts\        UI login accounts + permissions
  bop\             balance-of-performance entries
  groups\          permission groups
  presets, meta, databases, audit, login_sessions, .temp
  manager.json                   global manager settings (theme, custom CSS, favicon, …)
```

`config.yml` at the install root only configures the app itself (store path, monitoring,
account overrides) — not race content.

## Championship data model (a championship is TWO linked object types)

There is no single "championship config". A championship is a **championship object plus one
preset per round**:

| Store file | Holds | Does **not** hold |
|---|---|---|
| `championships/<champID>.json` | Name, Description, **Points** table, `EntryList`, and `Events[]` — each Event has an **ID** and a set of **Sessions** (Practice=Type 0 / Qualifying=1 / Race=2) with `Duration` in **nanoseconds**. | **Track. Weather.** Neither appears anywhere in the championship. |
| `presets/<eventID>.json` | `Data.RaceConfig` — the **track** (e.g. `"spa"`), weather (`ambientTemp`, `trackTemp`, `cloudLevel`, `rain`, `weatherRandomness`), and `sessions[]` with `sessionDurationMinutes`. Plus `Data.EventRules / Assists / ServerOptionsOverride / SignUpForm`. | — |

**The join (this took three failed deploys to pin down — do not re-guess it):**

1. **`event.ID == preset.ID`** — each event is configured by the preset whose file/`ID` **equals
   the event's ID**. The preset filename *is* the event ID.
2. `preset.Data.RaceConfig.metaData` = `"championship:<champID>:<eventID>"` (same eventID).
3. The **3 session UUIDs (FP/Q/R) are a shared template** reused by *every* event and *every*
   preset in the championship — they are **not** a per-event key. (Earlier notes here claimed the
   session UUIDs were the join; that was wrong.)
4. Non-deleted objects carry `"Deleted": "0001-01-01T00:00:00Z"`. A `null` makes the Go
   `time.Time` skip the object.

Get any of these wrong and the manager silently shows **"0 events configured"** even though the
events are in the file — its name/points still render, which makes the failure look like a
rendering bug rather than a bad join. A raw file-drop of a *brand-new* championship (fresh IDs)
reproduces this; the reliable path is to transform the manager's own files, preserving their IDs.

> **Duration can drift.** Session duration is stored twice — championship `Duration` (ns) *and*
> preset `sessionDurationMinutes`. A hand-edit can leave them disagreeing (the original "Q2 A"
> had a round reading 30 min in the championship but 60 min in the preset). The ACC-effective
> value is the preset's minutes; the tooling writes both from one source.

### Automating championship setup

`scripts/acc-championship/` has the tools (full detail in its `README.md`):

- **`remap.py`** (verified) — rewrites an existing championship's schedule by transforming the
  manager's own championship + preset files in place, **preserving every event/preset ID**, and
  changing only track/weather/time/race-length. This is how the Q2 2026 calendar was applied.
- **`gen.py`** (unverified for from-scratch) — generates a new championship using the correct
  model; use it only after the empty championship exists in the UI.

Deploy with `ansible/deploy-acc-championships.yml` (stops the service, backs up, swaps, restarts).
The store is read **at startup**, so a restart is required.

**Round start times** live on the preset, not the championship: `ScheduleEnabled: true` plus
`Schedules` — a dict **keyed by server index** (`"0"`, `"1"`, …) whose value has
`ScheduledTime` / `InitialScheduledTime` (real-world clock, e.g. `2026-08-03T18:00:00+02:00`). So
each championship's schedule is pinned to a specific ACC server (Q2 A → server 0, Q2 B → server 1
for the 2026 season). This real-world start is separate from `RaceConfig.sessions[].hourOfDay`
(the in-sim time of day). `remap.py` sets it from each round's `date` + `race_start_time`.

## Global look-and-feel: `store.json\manager.json`

Holds `Name`, `Theme` (`auto`), `darkMode`, `CustomCSS` (the MNR green/orange theme, incl. the
navbar-brand logo), `faviconURL`, `serverNameTemplate`, and API/crawler toggles.

> **Favicon (fixed 2026-07-26).** Both `faviconURL` and the `CustomCSS` `.navbar-brand
> { background-image: url(...) }` rule used to point at `https://dev.rablab.co.za/favicon.png`,
> which **404'd** after `dev.rablab.co.za` was removed on 2026-07-24. Both were repointed to
> `https://mondaynightracing.co.za/favicon.png` (the live MNR logo). `manager.json` is only
> re-read on service restart, so the change landed on the service cut-over. If it breaks again,
> a data-URI would remove the cross-host dependency entirely.

## Web API

Read-only. A handful of `GET …/*.json` endpoints expose results / championship data; there are
**no write/control endpoints** (you cannot create/start/schedule via the API — that's UI or the
store-file layer). Gated by the accounts permission system; unauthenticated reads need "Public
Access" enabled per endpoint. Rate-limited to ~5 requests / 20 s. Note some endpoints (e.g.
`GET /api/championship/list.json`) require **v1.5.3+**, so on 1.4.6 expect a smaller set.

## Secrets

The ACC driver / spectator / admin passwords live in
`store.json\servers\server_N\serverOptions.json` (under `serverSettings`), **not** in
championship or preset objects (the preset `ServerOptionsOverride.password` is empty). They are
deliberately **not** recorded in this repo; if rotated, put them in `vault.yml` as
`vault_acc_*_password` rather than in a doc.

## Deploy / restart caveat

The manager reads its JSON store **once, at startup**. Any file-level change (championship,
`manager.json` edit) needs a service restart to take effect. Now that it is a service the restart
is a `Restart-Service acc-server-manager` (no RDP needed), which `deploy-acc-championships.yml`
does for you. But the restart still takes down the running `accServer` instances, so treat it like
the Palace `start` tag — **off-peak only**, and check `Get-Process accServer` first.

## Web API

Read-only JSON API shared with the AC EVO manager (same product family) —
see **[server-manager-api.md](server-manager-api.md)**.

> **This manager has "Public Access" enabled and the EVO one does not.** As of 2026-08-18
> `https://acc.mondaynightracing.co.za/api/championship/list.json` and `/api/results/list.json`
> return 200 with **no credentials**, exposing 116 pages of race history, championship names and
> driver GUIDs. Almost certainly unintentional — worth deciding deliberately rather than leaving
> the two managers inconsistent.
