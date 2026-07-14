# Assetto Corsa EVO dedicated server

The AC EVO race server for Monday Night Racing. Runs on `mnr-race` (see
[mnr-server.md](mnr-server.md) for the host itself), out of a folder on the `MNR`
user's desktop — **not** a service, not under `Program Files`, not managed by Steam
on the server side.

| | |
|---|---|
| Install dir | `C:\Users\MNR\Desktop\mnr\ACEvo_Latest` |
| Server name | `MNR \| Monday Night Racing` |
| Game port | **34597** TCP + UDP (listener *and* internal are both set to 34597) |
| HTTP port | 8080 |
| Max players | 19 |
| Results | `...\ACEvo_Latest\results\` — one JSON per session |
| Log | `...\ACEvo_Latest\serverConfig\Assetto Corsa EVO Server.txt` |

## How it starts

**By hand.** There is no scheduled task, no service, and nothing in any Startup
folder — verified 2026-07-13. Someone RDPs/consoles in and starts it, and it stays
up for weeks (the instance running on 2026-07-13 had been up since 2026-06-08).

If nobody starts it, there is no race. Worth knowing before a Monday.

Two processes are involved:

- `ServerLauncher.exe` — a .NET GUI front-end (`ServerLauncher.dll` is the actual
  ~23 MB payload). This is the thing you launch and the thing that stays resident.
- `AssettoCorsaEVOServer.exe` — the game server proper. The launcher spawns it.

So `Get-Process ServerLauncher` is the "is the server up?" check.

## Config lives in the command line, not in a file

This is the part that surprises people. There is no `server_cfg.ini` equivalent for
AC EVO. The launcher passes the **entire** server and session config as two encoded
blobs on the `AssettoCorsaEVOServer.exe` command line:

```
AssettoCorsaEVOServer.exe -serverconfig <blob> -seasondefinition <blob>
```

Each blob is: **base64 → 4-byte big-endian uncompressed length → zlib deflate → JSON.**

`scripts/acevo-decode-launch.py` decodes them. Feed it a blob (or a whole
`.bat` line) and it prints the JSON:

```bash
python3 scripts/acevo-decode-launch.py AAACoXic...
```

`-serverconfig` carries ports, server name, max players, the allowed-cars list,
results path, and the **driver / admin / spectator passwords**. `-seasondefinition`
carries the session: track, layout, duration, time of day, weather, initial grip.

> The passwords are in that blob in plaintext once decoded. They are deliberately
> **not** written down in this repo. Decode a launch command to read them, or look
> in the ServerLauncher GUI. If they ever get rotated, put them in `vault.yml` as
> `vault_acevo_driver_password` / `vault_acevo_admin_password` rather than in a doc.

### Editing config

Use the ServerLauncher GUI — it builds the blobs for you. Hand-crafting a blob is
possible (base64(len + zlib(json))) but there is no validation on the far side, so a
malformed one just fails at startup.

`Backup_2026-06-06\ac_evo_launch.bat` is a *snapshot* of one such generated command,
kept from a previous round. It is not the live launch path and is not what ran on
2026-07-13 — the config in the 2026-07-13 log has a `tuning_type` field the June
`.bat` doesn't, so the GUI regenerates these per run. Treat the `.bat` as a worked
example, not as the source of truth.

### `cars.json` / `events_practice.json` / `events_race_weekend.json`

These sit at the install root and differ from Steam stock. Assume they are
league-tuned and **do not overwrite them from a Steam copy** without checking. They
were deliberately left alone in the 2026-07-13 update.

## Updating from Steam

The server has no Steam client. Updates are done by installing/updating **Assetto
Corsa EVO Dedicated Server** in Steam on a workstation and pushing the files up over
WinRM.

Workstation source path:

```
C:\Program Files (x86)\Steam\steamapps\common\Assetto Corsa EVO Dedicated Server
```

Procedure (this is what 2026-07-13 did):

1. **Stop the launcher.** `ServerLauncher.exe` and `ServerLauncher.dll` are locked
   while it runs — the copy will fail with a sharing violation. `Stop-Process -Name
   ServerLauncher -Force`.
2. **Back up what you're about to overwrite**, on the server (disk-local copy, free
   and fast — do not pull 360 MB down the VPN just to back it up):
   `Copy-Item foo foo.bak-<yyyymmdd>`.
3. **Copy** the binaries + `content.kspkg`.
4. **Verify by hash**, don't trust "changed: true". Compare `Get-FileHash` on the
   server against `sha256sum` locally.
5. **Leave the launcher stopped** unless you're ready to bring the server back up.

### Which files to copy

Hash both sides first and only copy what actually differs — most of the folder is
usually unchanged. As of 2026-07-13 the moving parts were:

- `AssettoCorsaEVOServer.exe`
- `ServerLauncher.exe`, `ServerLauncher.dll`
- `content.kspkg` (~260 MB, the slow one)
- Steam runtime: `steamclient.dll`, `steamclient64.dll`, `steamwebrtc.dll`,
  `steamwebrtc64.dll`, `tier0_s.dll`, `tier0_s64.dll`, `vstdlib_s.dll`,
  `vstdlib_s64.dll`

Usually unchanged: `evo.ico`, `libcrypto-3-x64.dll`, `libssl-3-x64.dll`,
`OptickCore.dll`, `steam_api64.dll`, `WinPixEventRuntime.dll`,
`ServerLauncher.deps.json`, `ServerLauncher.runtimeconfig.json`.

Never touch: `serverConfig\`, `results\`, `linux64\`, `*.so`, `Backup_*\`.

### Gotchas

- **The Steam path has spaces in it.** Ansible's ad-hoc `-a 'src=... dest=...'`
  form splits on whitespace and will fail with *"win_copy has extra params"*. Use a
  playbook with proper YAML values, not `-m win_copy -a`.
- **`content.kspkg` can shrink between versions.** The 2026-07-13 update took it
  from 359.7 MB down to 261.1 MB. That looked alarming but is what Steam shipped.
  Check the `.bak` before assuming content is missing.
- **Disk is tight.** `C:` had 4.4 GB free after the 2026-07-13 update. A 360 MB
  backup is a meaningful chunk of that. Clear old `.bak-*` files and stale
  `Backup_*\` folders once a new build is confirmed good.
- WinRM copies of a ~260 MB file take a while. Run them in the background.

## Known noise in the log

```
[network] [error] Could not bind TCP listener socket
```

Appears on every start and the server works anyway. The config sets
`server_tcp_internal_port` and `server_tcp_listener_port` to the *same* value
(34597), and the log line immediately above it says it's opening the internal socket
"instead of" the listener — so the listener bind is a duplicate on an
already-bound port. Believed benign; not investigated further.

## Backend

The server registers itself with Kunos' lobby over a websocket
(`wss://c.gk.sd:6990/...`) and pulls a season GUID from it. So it needs **outbound**
internet, not just the inbound game port. If the server starts but nobody can see it
in the browser, check that websocket connected in the log before blaming the port.

No firewall rule on `mnr-race` matches evo/assetto/launcher by name — inbound 34597
is presumably allowed further up (edge/NAT), not by a named local rule.

## State on disk

```
ACEvo_Latest\
  AssettoCorsaEVOServer.exe     game server
  ServerLauncher.exe/.dll       GUI front-end (start this)
  content.kspkg                 game content package (~260 MB)
  cars.json, events_*.json      league-tuned, leave alone
  serverConfig\
    Assetto Corsa EVO Server.txt   the log
    guid_map.carhashguid
    account.printabledriveraccount
  results\                      results_<ts>_{practice,qualify,race}.json
  linux64\, *.so                Linux artifacts, unused on Windows, harmless
  Backup_2026-06-06\            old build + the example ac_evo_launch.bat
```

Race nights show up in `results\` as a practice/qualify/race trio, ~19:00–20:10.
