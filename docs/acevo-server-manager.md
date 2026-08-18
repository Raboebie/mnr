# AC EVO Server Manager (acevo.mondaynightracing.co.za)

Web manager for the Assetto Corsa **EVO** race server — Emperor Servers' **"One Server
Manager" v1.6.3**, the same product family as the ACC manager
([acc-server-manager.md](acc-server-manager.md)) but a different build and a different
install. Distinct again from the hand-launched EVO server documented in
[acevo-server.md](acevo-server.md).

Installed 2026-08-09. Added to the public landing page 2026-08-18.

| | |
|---|---|
| Host | `mnr-race` (`10.104.0.10`) |
| Install dir | `C:\Users\MNR\Desktop\mnr\ACEvoManager` |
| Manager exe | `acevo-server-manager.exe` (~42 MB) |
| Web UI bind | `0.0.0.0:8774` (`hostname:` in `config.yml`; TLS off — Apache terminates) |
| Public URL | `https://acevo.mondaynightracing.co.za` |
| Store | `store.json\` — JSON store, one file per object (`accounts`, `championships`, `presets`, `servers`, `groups`, `databases`, `audit`, `meta`) |
| Game server | `AssettoCorsaEVOServer.exe` + `content.kspkg` in the **same** directory (`install_path` points at itself) |
| License | `ACEVO.License` — paid product |
| Logs | `server-manager.log`, `server.log` in the install dir |

## How it starts

Runs as the NSSM service **`acevo-server-manager`** (installed 2026-08-18 by
`ansible/deploy-acevo-manager-service.yml`): `Automatic` start so it comes up on boot,
`AppExit Default Restart` for crash-restart, running as `.\MNR`, `AppDirectory` set to the
install dir so it finds its own `store.json`. Service logs at `…\ACEvoManager\logs\service-*.log`.

```powershell
Get-Service acevo-server-manager        # the up-check
Restart-Service acevo-server-manager    # works over WinRM, no RDP needed
```

Crash-restart was verified on install: killing the process produced a new PID within ~12s and
`/healthcheck.json` came back `OK`.

> Until 2026-08-18 this was a bare hand-started process, so a reboot silently took
> `acevo.mondaynightracing.co.za` offline (Apache stays up and returns 503) until someone
> RDP'd in. Same gap the ACC manager had before it was wrapped in NSSM on 2026-07-26.

`config.yml` has `disable_windows_browser_open: true` — a service has no desktop session, so
the manager must not try to launch a browser on start. The playbook sets this and keeps a
`config.yml.bak-svc` alongside it.

To roll back to a hand-started process:

```powershell
nssm stop acevo-server-manager; nssm remove acevo-server-manager confirm
```

## Web API

The manager exposes a small read-only JSON API (championships, standings, results, plus a
public `/healthcheck.json`). Endpoints, auth, rate-limit traps and a helper script are
documented in **[server-manager-api.md](server-manager-api.md)**.

## Serving

Apache reverse-proxies it. The vhost is **repo-managed**:

- Template: `ansible/templates/httpd-acevo.conf.j2`
- Rendered to: `C:\Apache24\conf\extra\httpd-acevo.conf`, `Include`d at the end of `httpd.conf`
- Deploy: `ansible-playbook deploy-mnr-website.yml --tags apache` (then `--tags restart`
  off-peak — the restart bounces the single shared `httpd.exe` and blips every vhost)

It proxies `/` plus a WebSocket upgrade to `http://10.104.0.10:8774/`, on the
`mondaynightracing.co.za` wildcard cert.

### The ams2 subdomain also lands here

`ams2.mondaynightracing.co.za` (in `httpd-vhosts.conf`, unmanaged) points at the same port
8774 and therefore now serves the **AC EVO** manager. That is not a mistake to fix in a
hurry — AMS2 is no longer running on this box at all, and the old name is left working so
existing bookmarks and Discord links don't break. If you ever retire it, 301 it to
`acevo.` rather than deleting the vhost.

## Relationship to the other EVO install

`C:\Users\MNR\Desktop\mnr\ACEvo_Latest` — the hand-launched EVO server from
[acevo-server.md](acevo-server.md) — still exists, and `ACEvoManager` carries its **own**
copy of `AssettoCorsaEVOServer.exe`, `content.kspkg` (~260 MB), `cars.json` and the
`events_*.json` league-tuned files. So there are two full EVO server installs on a disk that
had **2.23 GB free** as of 2026-08-18 (down from 4.4 GB in July).

As of 2026-08-18 `ServerLauncher` is **not** running, i.e. the old hand-launched path is
idle and the manager is the live one. Confirm that before reclaiming anything, then consider
retiring `ACEvo_Latest` — it is the single biggest easy win on that disk.
