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
dns/
  mondaynightracing.co.za.zone   cleaned BIND export for the CF import
docs/
  mnr-server.md                  host, Apache vhost map, certs, gotchas
  acevo-server.md                AC EVO race server: layout, launch, Steam update procedure
  website-c-website.md           dev.rablab.co.za DocumentRoot inventory
  website-c-mnr_website.md       mondaynightracing.co.za DocumentRoot inventory
  dns-cloudflare-migration.md    mnr.co.za DNS migration state and procedure
scripts/
  posh-acme-setup.ps1            one-time cert issuance + deploy (run as SYSTEM, takes -CFToken)
  posh-acme-renew.ps1            daily renewal on server (deployed at C:\certs\_acme\renew.ps1)
  acevo-decode-launch.py         decode AC EVO -serverconfig/-seasondefinition blobs to JSON
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

## Uploading files via WinRM

`pywinrm`'s `run_ps` caps a single script at ~3000 characters. For binary uploads (certs, keys), base64-encode locally and append in chunks of ~2500 chars to a staging `.b64` file on the server, then decode with `[Convert]::FromBase64String` + `[IO.File]::WriteAllBytes`. There is a reference implementation in the git history under the 2026-04-24 cert deploy.

For bulk file pushes, `win_copy` in a **playbook** handles chunking for you and is much less painful. Do not use the ad-hoc `-m win_copy -a 'src=... dest=...'` form when either path contains spaces (e.g. the Steam install dir) — ad-hoc args split on whitespace and it fails with *"win_copy has extra params"*. Note also that a failed `ansible-playbook` inside a backgrounded shell pipeline can still report exit 0 from the wrapping command — check the play recap, not just the exit code.

## Things to be careful about

- **Do not touch `C:\Apache24\conf\api.conf` or `extra\httpd-mnr.conf`** on the server — they are orphaned (not included by `httpd.conf`) but editing them gives a false sense of effect. Live vhosts are only in `extra\httpd-vhosts.conf`.
- `httpd-ssl.conf` is intentionally empty; SSL globals are configured per-vhost.
- `C:\Certbot\csr\` and `keys\` have ~120 leftover files from a broken 2021 auto-renew loop. Harmless but visually noisy.
- The `mnr` account works over WinRM only because `LocalAccountTokenFilterPolicy=1` is set in the registry. If someone wipes that key, remote auth starts failing with `InvalidCredentialsError` despite correct creds.
- **`C:` is tight on space** — 4.4 GB free as of 2026-07-13. `ACEvo_Latest\content.kspkg` alone is ~260 MB, and backups of it are the same again. Clear stale `.bak-*` files and old `Backup_*\` folders once a build is confirmed good, and check free space before pushing anything large.
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
