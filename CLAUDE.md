# Repo orientation

This repo is ops glue for the **Monday Night Racing** Windows server (`mnr-race`, `10.104.0.10`), the AC EVO race server it hosts, and related rablab-hosted domains. There is no application code here — it's infrastructure, docs, and Ansible.

## Layout

```
ansible/           Ansible control root (run commands from here)
  ansible.cfg
  inventory.yml
  group_vars/all/
    vars.yml       public vars (server paths, site list, VPN info, CF zone/account IDs)
    vault.yml      ansible-vault encrypted secrets (winrm, VPN, CF API token)
  .vault_password  random password for the vault (gitignored)
site/
  mnr_website/     landing page source of truth (deployed to C:\mnr_website)
dns/
  mondaynightracing.co.za.zone   cleaned BIND export for the CF import
docs/
  mnr-server.md                  host, Apache vhost map, certs, gotchas
  acevo-server.md                AC EVO race server: layout, launch, Steam update procedure
  acc-server-manager.md          ACC Server Manager (acc.mondaynightracing.co.za): store, championship model
  acevo-server-manager.md        AC EVO Server Manager (acevo.mondaynightracing.co.za): NSSM service on :8774
  server-manager-api.md          ACC + AC EVO manager Web API: endpoints, auth, rate-limit traps
  website-c-website.md           dev.rablab.co.za DocumentRoot inventory
  website-c-mnr_website.md       mondaynightracing.co.za DocumentRoot inventory (source now in site/)
  dns-cloudflare-migration.md    mnr.co.za DNS migration state and procedure
  disk-reclaim-2026-08-18.md     what was freed on C:, what must never be deleted
reference/
  acevo-config/    snapshot of the league-tuned AC EVO cars.json / events_*.json
scripts/
  posh-acme-setup.ps1            one-time cert issuance + deploy (run as SYSTEM, takes -CFToken)
  posh-acme-renew.ps1            daily renewal on server (deployed at C:\certs\_acme\renew.ps1)
  acevo-decode-launch.py         decode AC EVO -serverconfig/-seasondefinition blobs to JSON
  acc-championship/              generate ACC championship+preset JSON from a season.yml (gen.py)
  osm-api.sh                     query the ACC/EVO manager Web API (handles login from the vault)
vpn/
  mnr-jh1.ovpn     OpenVPN config (CA inlined) for the JH1 tunnel
```

## Working with the vault

- Encrypt/view/edit: `ansible-vault view group_vars/all/vault.yml` etc. (ansible.cfg already points at `.vault_password`, so no `--ask-vault-pass`).
- When adding a secret: put it in `vault.yml` as `vault_<name>: ...` and reference it from `vars.yml` as `<name>: "{{ vault_<name> }}"`. Keeps playbooks readable without `lookup('vault', ...)` noise.
- Never commit `.vault_password` or a decrypted `vault.yml`.

## Reaching the server

`10.104.0.10` is only reachable through the JH1 OpenVPN tunnel. Bring it up with the client of your choice using the ovpn config referenced in `vars.yml` (`vpn.ovpn_config`). The OpenVPN installer exe in `~/Downloads/ovpn/` is a 7z archive — `7z x` extracts the `.ovpn` and CA cert if you need to rebuild it.

Once connected, `ansible windows -m win_ping` from `ansible/` should return `pong`.

## Certificate renewal

- Source of truth for cert paths: `sites[*]` in `vars.yml`. That list matches what the live vhosts in `C:\Apache24\conf\extra\httpd-vhosts.conf` reference.
- Renewal is **out-of-band via `acme.sh`** on a workstation, then PEMs get copied up with WinRM. The server's own Certbot install (v1.13.0, 2021) is dead — ignore it.
- `mondaynightracing.co.za` → on Cloudflare (migrated 2026-04-24). Renewal is **fully automated on the server itself** via Posh-ACME — see below. This now covers every site the server serves.
  - (`rablab.co.za` was on Afrihost DNS with a manual DNS-01 workstation flow via `~/.acme.sh/`; no longer relevant since `dev.rablab.co.za` was removed 2026-07-24. If a rablab site returns, note Afrihost's 14400s TTL means LE's validator cache can persist up to 4h after a failed attempt.)

### Server-side automated renewal (mnr-race)

Set up 2026-04-24 using Posh-ACME v4.32.0 (installed from the PowerShell Gallery `.nupkg` directly, bypassing the broken NuGet provider bootstrap). State lives at `C:\certs\_acme\config` (POSHACME_HOME set machine-wide). The Cloudflare API token is stored DPAPI-encrypted inside that state, bound to SYSTEM.

Two certs are tracked: `mondaynightracing.co.za + *.mondaynightracing.co.za` and `timing.mondaynightracing.co.za`. A daily scheduled task `AcmeRenew` runs `C:\certs\_acme\renew.ps1` at 03:15 as SYSTEM. The script calls `Submit-Renewal`, which respects LE's 30-day window — on most days it's a no-op. When a cert does renew, the script copies the new fullchain+key into the paths `httpd-vhosts.conf` references and restarts `Apache2.4` (guarded behind `httpd -t` so a bad deploy leaves the running server untouched). Log at `C:\certs\_acme\renew.log`.

> **2026-07-24 incident:** the certs silently expired even though `Submit-Renewal` kept succeeding. Root cause: on the actual renewal day (2026-06-23) `renew.ps1` renewed both certs but crashed in its deploy loop — `Submit-Renewal` returns `PACertificate` objects whose domain is on `.Subject`, not `.MainDomain`, so `$deployMap.ContainsKey($null)` threw and the fresh PEMs never reached Apache. Fixed in `scripts/posh-acme-renew.ps1` (derive the domain from `.Subject` as a fallback, pull file paths from `Get-PACertificate`, and only restart after `httpd -t` passes). Lesson: a green "0 renewed / nothing to renew" log line is *not* proof the served cert is current — check the on-disk PEM's `NotAfter` against Posh-ACME's tracked `CertExpires`.

Canonical copies of the setup and renewal scripts are in `scripts/posh-acme-*.ps1`. If the server state is ever lost (reimage, disk failure), re-run the setup script as SYSTEM with `-CFToken` from the vault, re-register the daily task, and you're back.

`dev.rablab.co.za` was **removed** from the Apache config on 2026-07-24 (it was the only rablab-hosted site). Its two vhosts were replaced by default `*:80`/`*:443` vhosts that 301-redirect bare-IP access and any unmatched host to `https://mondaynightracing.co.za`. The old cert files under `C:\Certbot\live\dev.rablab.co.za\` are left in place but no longer served. Nothing on the server now needs the Afrihost manual DNS-01 renewal path.
- LE remembers apex validations per-account for 30 days, so wildcard re-issues only need the wildcard TXT after the first successful apex validation.
- Full context (and the 2026-04-24 renewal round) is in `docs/mnr-server.md`.

## AC EVO race server

Lives at `C:\Users\MNR\Desktop\mnr\ACEvo_Latest` on `mnr-race`. **Started by hand** — no service, no scheduled task, nothing in Startup. `Get-Process ServerLauncher` is the "is it up?" check.

Its config is not in a file: the launcher passes the whole thing as base64+zlib blobs on the `AssettoCorsaEVOServer.exe` command line (`-serverconfig`, `-seasondefinition`). Decode them with `scripts/acevo-decode-launch.py`. The driver/admin passwords live inside those blobs — if they're ever rotated, put them in the vault rather than in a doc.

Updates come from a Steam **Assetto Corsa EVO Dedicated Server** install on a workstation, pushed up over WinRM. Stop the launcher first (it locks its own exe/dll), hash-compare both sides, copy only what differs, and verify by hash afterwards. `cars.json` and `events_*.json` are league-tuned — don't overwrite them with Steam stock. Full procedure in `docs/acevo-server.md`.

## AC EVO Server Manager (acevo.mondaynightracing.co.za)

Emperor Servers **"One Server Manager" v1.6.3** at `C:\Users\MNR\Desktop\mnr\ACEvoManager`, bound to
`0.0.0.0:8774` and reverse-proxied by Apache. Installed 2026-08-09; linked from the landing page 2026-08-18.
Same JSON-store design as the ACC manager (`store.json\`, one file per object), but its own install — it
carries its own `AssettoCorsaEVOServer.exe` + `content.kspkg`, separate from `ACEvo_Latest`.

Runs as the NSSM service **`acevo-server-manager`** (Auto start, crash-restart, as `.\MNR`) — set up
2026-08-18 via `ansible/deploy-acevo-manager-service.yml`; before that it was a bare hand-started process that
did not survive a reboot. `Get-Service acevo-server-manager` is the up-check;
`Restart-Service acevo-server-manager` works over WinRM. The playbook refuses to run while an event is in
progress (it stops the manager and its game servers) — override with `-e force_stop=true`.

`ams2.mondaynightracing.co.za` proxies the **same** port 8774, so it now serves AC EVO too. AMS2 itself is no
longer running on the box. `acevo.` is the canonical name; `ams2.` is left working for old bookmarks. Detail
in `docs/acevo-server-manager.md`.

## Landing page (mondaynightracing.co.za)

Source of truth is **`site/mnr_website/`** in this repo (snapshotted off the live server 2026-08-18 — before
that the server was the only copy). DocumentRoot `C:\mnr_website`. Deploy from `ansible/`:

```bash
ansible-playbook deploy-mnr-website.yml --tags site      # static files. non-disruptive
ansible-playbook deploy-mnr-website.yml --tags apache    # renders the acevo vhost + httpd -t. no restart
ansible-playbook deploy-mnr-website.yml --tags restart   # DISRUPTIVE shared-httpd restart. off-peak only
```

Edit in the repo, never on the box — the next `site` run overwrites hand-edits. `stats.txt` (tracker.php's
counter) is runtime state: deliberately not in the repo, and the playbook copies without deleting so it
survives. `index.html` is CRLF; `.gitattributes` marks the dir `-text` to keep it byte-exact.

## ACC Server Manager (acc.mondaynightracing.co.za)

Separate from AC EVO: this is the **Assetto Corsa Competizione** platform — Emperor Servers' "ACC Server Manager" v1.4.6, a Go web app at `C:\Users\MNR\Desktop\mnr\Official Race Servers\Race` on `mnr-race`, bound to `:8773` and reverse-proxied by Apache (`acc.mondaynightracing.co.za`). Runs as the NSSM service **`acc-server-manager`** (Auto start, crash-restart, as `MNR-RACE\MNR`) — set up 2026-07-26; `Restart-Service acc-server-manager` over WinRM now, no RDP needed. It supervises up to three `accServer.exe` instances (A/B/C, GT3). `Get-Service acc-server-manager` / `Get-Process accServer` are the up-checks.

Config is a **JSON store** at `store.json\` (one file per object). The non-obvious bit: a championship is **two linked object types** — `championships\<id>.json` (points, entry list, events — *no track/weather*) plus one `presets\<id>.json` per round (track + weather in `Data.RaceConfig`). The join, learned the hard way: **`event.ID == preset.ID`** (the preset filename *is* the event ID), `metaData: championship:<champID>:<eventID>`, and the 3 FP/Q/R session UUIDs are a **shared template** across the whole championship (not a per-event key); `Deleted` must be the zero-time string, not `null`. Get any wrong → manager silently shows "0 events configured". Use `scripts/acc-championship/remap.py` to reschedule an existing championship (transforms the manager's own files in place, preserving IDs — the verified path); `gen.py` builds new ones but isn't verified for raw file-drop. Deploy via `ansible/deploy-acc-championships.yml` (restarts the service; **off-peak** — blips live `accServer`). ACC server passwords live in `store.json\servers\server_N\serverOptions.json`, not in championship/preset objects — vault them if rotated. Full detail in `docs/acc-server-manager.md`.

## Uploading files via WinRM

`pywinrm`'s `run_ps` caps a single script at ~3000 characters. For binary uploads (certs, keys), base64-encode locally and append in chunks of ~2500 chars to a staging `.b64` file on the server, then decode with `[Convert]::FromBase64String` + `[IO.File]::WriteAllBytes`. There is a reference implementation in the git history under the 2026-04-24 cert deploy.

For bulk file pushes, `win_copy` in a **playbook** handles chunking for you and is much less painful. Do not use the ad-hoc `-m win_copy -a 'src=... dest=...'` form when either path contains spaces (e.g. the Steam install dir) — ad-hoc args split on whitespace and it fails with *"win_copy has extra params"*. Note also that a failed `ansible-playbook` inside a backgrounded shell pipeline can still report exit 0 from the wrapping command — check the play recap, not just the exit code.

## Things to be careful about

- **Do not touch `C:\Apache24\conf\api.conf` or `extra\httpd-mnr.conf`** on the server — they are orphaned (not included by `httpd.conf`) but editing them gives a false sense of effect. Live vhosts are in `extra\httpd-vhosts.conf` **plus** the per-app files `Include`d at the end of `httpd.conf` (`httpd-palace.conf`, `httpd-manager.conf`, `httpd-acevo.conf`) — those three are rendered from templates, so edit the template and redeploy, never the server copy.
- `httpd-ssl.conf` is intentionally empty; SSL globals are configured per-vhost.
- `C:\Certbot\csr\` and `keys\` have ~120 leftover files from a broken 2021 auto-renew loop. Harmless but visually noisy.
- The `mnr` account works over WinRM only because `LocalAccountTokenFilterPolicy=1` is set in the registry. If someone wipes that key, remote auth starts failing with `InvalidCredentialsError` despite correct creds.
- **`C:` space** — was down to 2.23 GB free; **11.37 GB free after the 2026-08-18 cleanup** (see `docs/disk-reclaim-2026-08-18.md`). Nearly all of it came from one dormant `docker_data.vhdx`; a WinSxS `/StartComponentCleanup /ResetBase` was also run and freed **nothing**, so don't reach for that one again. Still check free space before pushing anything large, and clear stale `.bak-*` / `Backup_*\` folders once a build is confirmed good.
- **Do not delete `C:\feedback`.** It looks like an abandoned 2025 ASP.NET app and there is a *stopped* IIS site pointing at it, but `C:\feedback\WebApi.exe` is **live on port 8080** as a standalone process. It came within one command of being deleted during the 2026-08-18 disk cleanup.
- Don't overwrite the AC EVO `cars.json` / `events_practice.json` / `events_race_weekend.json` from a Steam copy — they differ from stock and look league-tuned.

## Palace deployment (palace.mondaynightracing.co.za)

The Palace card game (repo: `~/git/personal/shithead`, aka Shithead) runs on `mnr-race` as a
dev/beta host: the Expo **web client** served static by Apache, talking to the **`@palace/server`**
WebSocket gateway running as a Windows service. Deployed 2026-07-19.

**Build the artifacts first** (in the shithead repo):
```bash
pnpm --filter @palace/server build                      # -> apps/server/dist/server.js (esbuild bundle)
EXPO_PUBLIC_SERVER_URL="wss://palace.mondaynightracing.co.za/ws" \
  pnpm --filter @palace/client exec expo export -p web  # -> apps/client/dist/
```

**Then deploy** (from `ansible/`):
```bash
ansible-playbook deploy-palace.yml            # full run, or --tags dirs,node,nssm,artifacts,apache,service,start
```
Redeploy after a code change = rebuild the two artifacts + re-run the playbook. The `artifacts` tag
purges `C:\palace\web` before copying (Expo hashes bundle names, so stale chunks would otherwise pile
up on the tight C: disk). The **`start` tag is the only disruptive one** — it graceful-restarts the
single shared `httpd.exe`, briefly blipping every vhost (acc/ams2/timing/mnr) — run it off-peak.

**On-disk layout** (`C:\palace\`): `node\` (portable Node 22.12.0), `app\server.js` (the bundle),
`web\` (static export, DocumentRoot), `data\palace.db` (SQLite WAL, `PALACE_DATA_DIR`), `logs\`
(`out.log`/`err.log`), `tools\nssm.exe`.

**Service:** `palace-server`, an NSSM service — `node --experimental-sqlite server.js`, bound to
`127.0.0.1:8787` (loopback only; Apache is the sole ingress), `Start=SERVICE_AUTO_START` (boots) with
`AppExit Default Restart` (crash-restart). Check: `nssm status palace-server`, `Get-Content
C:\palace\logs\out.log -Tail 20`, `curl http://127.0.0.1:8787/health`.

**Apache:** vhost `conf\extra\httpd-palace.conf` (rendered from `ansible/templates/httpd-palace.conf.j2`,
`Include`d at the end of `httpd.conf`), wildcard cert `C:/certs/mondaynightracing.co.za/`. It serves the
static client and reverse-proxies the WebSocket (via `mod_proxy_wstunnel`, which this deploy added to
`httpd.conf`) + `/health` to the loopback gateway. DNS already resolves via the `*` wildcard record — no
Cloudflare change was needed.

**Known limitations (beta):** rooms are in-memory, so a service restart drops in-flight games; no
rate-limit / room-creation cap yet. The Skia canvas does not mount on the web build (renders via
react-native-web instead), so the burn/pickup visual effects don't show on web — a client-side follow-up,
not a server/deploy issue.

**Vault note:** the vault password was lost and **re-keyed** on 2026-07-19 (new password is in the
gitignored `ansible/.vault_password`, per the existing convention — never in a committed file). Only the
WinRM creds were recovered; `vault_vpn_*` and `vault_cloudflare_api_token` are `REPLACE_ME_*` placeholders — refill before
any VPN-bring-up or Cloudflare DNS automation).

## Server Manager Web API

Both managers (ACC v1.6.2, AC EVO v1.6.3 — same Emperor product) expose a small **read-only** JSON API:
`/healthcheck.json` (public), `/api/championship/list.json`, `/api/championship/{id}/standings.json`,
`/api/results/list.json`, `/server/{id}/result/download/{name}.json`. No write/control API exists — config
changes still mean editing the JSON store and restarting.

Use `scripts/osm-api.sh <acc|acevo> <endpoint>`; it logs in with `vault_osm_admin_password` (same `admin`
account on both) and caches the cookie. **Two traps:** exceeding the 5-requests-per-20-seconds limit returns
`302 → /login`, not `429`, so it looks exactly like a broken session; and the vendor's documented search
syntax `q=%2Bspa` returns HTTP 500 (plain `q=monza` works). Also note **ACC has Public Access enabled and EVO
does not** — ACC's championship and results endpoints are readable with no credentials at all. Full detail in
`docs/server-manager-api.md`.
