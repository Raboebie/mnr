# Server Manager Web API (ACC + AC EVO)

Both MNR race platforms run the **same Emperor Servers product** ("One Server Manager"), just
different game builds, so they share one API surface and one set of credentials:

| | ACC | AC EVO |
|---|---|---|
| Public URL | `https://acc.mondaynightracing.co.za` | `https://acevo.mondaynightracing.co.za` |
| Version (`/healthcheck.json`) | **v1.6.2** | **v1.6.3** |
| `Game` | `Assetto Corsa Competizione` | `Assetto Corsa EVO` |
| Install | `…\Official Race Servers\Race` | `…\mnr\ACEvoManager` |
| Docs | [acc-server-manager.md](acc-server-manager.md) | [acevo-server-manager.md](acevo-server-manager.md) |

> The ACC manager is on **v1.6.2**, not the v1.4.6 recorded in older notes — it has been updated.

The API is **read-only**. There is no write/control API: starting servers, editing championships
and uploading presets are all HTML form posts, not JSON endpoints. To change configuration,
manipulate the JSON store on disk and restart the service (see the per-manager docs).

Upstream reference: <https://wiki.emperorservers.com/en/assetto-corsa-evo-server-manager/web-api>.
The vendor gives no API versioning guarantee. **The AC1 "Server Manager v2" wiki page documents a
different, larger endpoint set (`/api/live-timings/*`, `/api/championships/list.json` plural,
`/race-control/penalties-log.json`) — none of those exist on v1.6.x. Verified 404.**

## Endpoints

All verified live on both managers, 2026-08-18.

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /healthcheck.json` | **public** | version, uptime, and per-server live state |
| `GET /api/championship/list.json` | account | all championships + links to their standings |
| `GET /api/championship/{championshipID}/standings.json` | account | driver + team standings |
| `GET /api/results/list.json` | account | paged session results index |
| `GET /server/{serverID}/result/download/{name}.json` | account | **manager-format** result (use this) |
| `GET /server/{serverID}/results/download/{name}.json` | account | raw game-format result |

Note the singular `championship` in the path and the singular/plural split between
`/result/download/` and `/results/download/` — both are easy to get wrong.

### `/healthcheck.json` — the useful public one

No auth, no session, one request. Good enough to drive a live status widget:

```console
$ curl -s https://acevo.mondaynightracing.co.za/healthcheck.json
{
  "OK": true, "Version": "v1.6.3", "Game": "Assetto Corsa EVO",
  "Uptime": "198h6m7s", "OS": "windows/amd64", "GoVersion": "go1.26.4",
  "EventInProgress": false,
  "Servers": {
    "0": {
      "ServerName": "MNR | Monday Night Racing",
      "ChampionshipName": "Fun Evo", "TrackName": "Monza (GP) - GP Race",
      "CurrentSession": "", "NumConnectedDrivers": -1,
      "EventInProgress": false, "EventIsChampionship": true
    }
  }
}
```

`NumConnectedDrivers: -1` means "server not running" — it is not a count of zero.

> **This endpoint is public and unauthenticated**, and it leaks `LicenseID`, host uptime, Go
> version and internal server names. If that matters, put it behind Apache (`<Location
> /healthcheck.json>`) rather than looking for a manager setting.

### Championships and standings

```console
$ curl -s -b jar https://acevo.mondaynightracing.co.za/api/championship/list.json
{"championships":[{"name":"Fun Evo","id":"2b2cffee-…","progress":100,
  "championship_standings_json_url":"/api/championship/2b2cffee-…/standings.json",
  "championship_page_url":"/championship/2b2cffee-…"}]}
```

The list hands you the follow-up URLs — don't hand-build them. Standings are
`{"DriverStandings": {...}, "TeamStandings": {...}}`, each **keyed by class ID** (`""` for a
single-class championship), each value an array with `DriverName`, `DriverGUID`, `Nation`,
`CarModel`, `Points`, `PointsPenalty`, `Position`. `TeamStandings[""]` is `null` when teams
aren't used.

### Results

`/api/results/list.json` is an index, and like the championship list it hands you the URLs:

```json
{
  "num_pages": 1, "current_page": 0, "sort_type": "date",
  "results": [{
    "track": "Monza", "manager_session_type": "Race", "server_id": 0,
    "date": "2026-08-17T19:42:53Z",
    "results_json_url":                 "/server/0/results/download/results_20260817_194253_race.json",
    "server_manager_results_json_url":  "/server/0/result/download/2026-08-17_19-42-53_RACE.json",
    "results_page_url":                 "/server/0/results/2026-08-17_19-42-53_RACE"
  }]
}
```

**Two different result formats, and the difference matters:**

- `server_manager_results_json_url` (`/result/download/`) — **the one you want.** A `Places[]`
  array already sorted by finishing order: `Position`, `DriverName`, `DriverGUID`, `CarModel`,
  `RaceNumber`, `Team`, `TotalRaceTime`, `TimePenalty`, `Disqualified`, `Laps`, plus
  `Collisions`, `IsWetSession`, `TrackID`.
- `results_json_url` (`/results/download/`) — the raw game dump. On AC EVO its top level is
  `car_standings` / `driver_standings` / `laps` / `collisions`, and cars are identified by a
  128-bit `car_id: {a, b}` pair you have to join yourself. Only worth it for telemetry-level
  detail (fuel, tyre wear, per-lap data).

Query params: `?page=<n>&sort=date&q=<search>`.

> **Gotcha: the wiki's own search example is broken.** `q=%2Bspa` (a leading `+`) returns
> **HTTP 500** on both managers. Plain `q=monza` works. Verified 2026-08-18.

## Authentication

Session-cookie based — there are **no API tokens**. POST the login form, keep the cookie:

```bash
curl -s -c jar -X POST \
  --data-urlencode "Username=admin" --data-urlencode "Password=<vault: osm_admin_password>" \
  https://acevo.mondaynightracing.co.za/login          # 302 -> /  on success
curl -s -b jar https://acevo.mondaynightracing.co.za/api/championship/list.json
```

The cookie is `HttpOnly` and named per install (e.g. `Regologeon_Evo1_osm_data`). The same
`admin` account and password work on **both** managers. The password lives in the vault as
`vault_osm_admin_password` — never in this repo, a script, or a shell history line.

Per-endpoint access is governed by the manager's own account permissions ("Championships Api
List", "Results Api List", …), and unauthenticated access requires the account system's
**Public Access** to be switched on.

> **The ACC manager currently has Public Access enabled and AC EVO does not.**
> `https://acc.mondaynightracing.co.za/api/championship/list.json` and `/api/results/list.json`
> return 200 with **no credentials** — 116 pages of race history, championship names and driver
> GUIDs are world-readable. AC EVO returns 302 → `/login` for the same paths. That asymmetry is
> almost certainly unintentional; decide whether ACC should be locked down or EVO opened up,
> rather than leaving them inconsistent.

## Rate limiting — read this before writing a poller

**5 requests per 20 seconds.** The vendor recommends no more than twice a minute.

The trap: when you exceed it, the manager does **not** return `429`. It returns **`302 → /login`**,
exactly as if your session were invalid. Chasing a "login isn't working" bug that is really the
rate limiter costs a lot of time — if authenticated calls suddenly start redirecting, wait 20
seconds before touching the credentials.

## Helper script

`scripts/osm-api.sh` wraps login, cookie reuse and pretty-printing:

```bash
scripts/osm-api.sh acevo /healthcheck.json           # public, no login
scripts/osm-api.sh acevo /api/championship/list.json # logs in, caches the cookie
scripts/osm-api.sh acc   /api/results/list.json
```

It reads the password from the vault, so it never appears on the command line.
