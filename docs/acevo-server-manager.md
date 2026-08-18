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

**Nothing starts it.** It is a bare process launched by hand — no Windows service, no
scheduled task, nothing in Startup. It does not survive a reboot.

```powershell
Get-Process acevo-server-manager        # the up-check
```

This is the same gap the ACC manager had before it was wrapped in NSSM on 2026-07-26. Until
that is done here, a reboot silently takes `acevo.mondaynightracing.co.za` offline (Apache
stays up and returns 503) and someone has to RDP in to start it. **Wrapping it in an NSSM
service is the obvious follow-up** — see the `acc-server-manager` setup in
[acc-server-manager.md](acc-server-manager.md) for the pattern.

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
