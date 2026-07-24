# mnr-race server

Windows host that serves the Monday Night Racing web properties. Reached over the JH1 OpenVPN tunnel. (`dev.rablab.co.za` was removed 2026-07-24 — bare-IP and unmatched hosts now redirect to the main site.)

## Host facts

| | |
|---|---|
| Hostname | `mnr-race` |
| OS | Windows 10 Pro |
| Workgroup | `WORKGROUP` (not domain-joined) |
| LAN IP | `10.104.0.10` |
| WinRM | `http://10.104.0.10:5985/wsman`, NTLM, local user `mnr` |

`mnr` is in **Administrators** and `docker-users`. `Password required: No` flag is set on the account (password exists but is not required by policy). `Password last set: 2021/02/26`.

### WinRM remote-auth fix

Local-admin accounts on workgroup machines get a filtered token over the network. Without the registry override below, WinRM rejects valid credentials with `InvalidCredentialsError`.

```powershell
New-ItemProperty `
  -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
  -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
```

Also required:
- All NIC profiles set to Private (not Public) — otherwise WinRM firewall exception refuses to activate.
- `Set-Item WSMan:\localhost\Service\AllowUnencrypted $true` for HTTP NTLM.

### Network reach

VPN: OpenVPN config committed at `vpn/mnr-jh1.ovpn` (CA already inlined under `<ca>...</ca>`). VPN endpoint: `41.76.226.14:1194 tcp4`, auth-user-pass — creds in the vault as `vault_vpn_username` / `vault_vpn_password`. Original Windows installer was `~/Downloads/ovpn/openvpn-JH1-ISP-NSX-T_VPN_PFSESE-TCP4-1194-install-2.6.5-I001-amd64.exe`, a 7z archive — `7z x` extracts the config and CA cert if you ever need to rebuild.

## Apache

Apache Haus 2.4 installed at `C:\Apache24`. Service `Apache2.4`, running. Listens on 80 and 443 (plus 8773 which is a separate app, not Apache).

### Active config

`httpd.conf` includes:
- `conf/extra/httpd-vhosts.conf` — all live vhosts
- `conf/extra/httpd-ssl.conf` — present but **empty** (0 bytes)

The SSL globals (protocols, ciphers, `SSLSessionCache`, etc.) live in `conf/extra/httpd-ahssl.conf`, which is **not** currently included — per-vhost `SSLProtocol`/`SSLCipherSuite` lines handle that inline instead.

### Orphaned / unused configs

| File | Status |
|---|---|
| `C:\Apache24\conf\api.conf` | vhost for `api.buzzworx.co:8443`, not included by `httpd.conf`. Cert files in `C:\Certbot\live\api.buzzworx.co\*` are all 0 bytes (broken Certbot state from 2021). |
| `C:\Apache24\conf\extra\httpd-mnr.conf` | duplicate `timing.mondaynightracing.co.za` vhost, not included. Safe to leave. |
| `C:\Certbot\csr\*` and `C:\Certbot\keys\*` | ~120 files from an old Certbot auto-renew loop that ran many times daily in 2021. Not touched since. Can be archived. |

### Vhosts (live)

All in `conf/extra/httpd-vhosts.conf`:

| ServerName | Port | Backend | DocumentRoot | Cert path |
|---|---|---|---|---|
| `mnr-default` (default) | 80 | — | — | HTTP→HTTPS; bare-IP/empty host → `https://mondaynightracing.co.za` |
| `mnr-default-ssl` (default) | 443 | — | — | bare-IP/unmatched-SNI → 301 `https://mondaynightracing.co.za` (mnr wildcard cert, mismatch expected) |
| `timing.mondaynightracing.co.za` | 443 | proxy `http://10.104.0.10:8773/` + WS upgrade | `C:/website` | `C:\certs\timing.mondaynightracing.co.za\certificate.cer` + `private.key` |
| `mondaynightracing.co.za` | 443 | static PHP/HTML, SPA fallback to `/index.html` | `C:/mnr_website` | `C:\certs\mondaynightracing.co.za\fullchain.pem` + `privkey.pem` |
| `acc.mondaynightracing.co.za` | 443 | proxy `http://10.104.0.10:8773/` + WS upgrade | — | same as apex (wildcard SAN) |
| `ams2.mondaynightracing.co.za` | 443 | proxy `http://10.104.0.10:8774/` + WS upgrade | — | same as apex (wildcard SAN) |

All SSL vhosts use:
```
SSLProtocol -all +TLSv1.2 +TLSv1.3
SSLCipherSuite HIGH:!aNULL:!MD5:!RC4
SSLHonorCipherOrder on
HSTS: max-age=63072000; includeSubDomains; preload
```

## Certificates

Certbot 1.13.0 (stale, 2021) is installed at `C:\Program Files (x86)\Certbot\bin\certbot.exe` but its `live/` dir contains zero-byte files — broken and ignored. The live automation path is **Posh-ACME on the server** for the two MNR certs (mondaynightracing.co.za wildcard + timing), driven by a daily SYSTEM scheduled task. This now covers every cert the server serves (`dev.rablab.co.za` was removed 2026-07-24).

> **2026-07-24 renewal incident:** both certs silently expired (2026-07-23) even though the daily task logged success. Posh-ACME had renewed them on 2026-06-23 (valid to 2026-09-21), but `renew.ps1` crashed in its deploy loop — `Submit-Renewal` returns `PACertificate` objects whose domain is on `.Subject`, not `.MainDomain`, so `$deployMap.ContainsKey($null)` threw and the fresh PEMs never reached Apache. Fixed in `scripts/posh-acme-renew.ps1` (Subject fallback + `Get-PACertificate` paths + `httpd -t` gate before restart). The CF API token was also rotated into the vault and re-saved into Posh-ACME state as SYSTEM (verified decryptable + valid). **When auditing renewal, compare the on-disk PEM's `NotAfter` against Posh-ACME's tracked `CertExpires` — a "nothing to renew" log line does not prove the served cert is current.**

### Posh-ACME on-server automation

Installed 2026-04-24. Key facts:

- Version 4.32.0, pulled as a `.nupkg` directly from PowerShell Gallery and extracted into `C:\Program Files\WindowsPowerShell\Modules\Posh-ACME\4.32.0` (the usual `Install-Module` route hung on a NuGet-provider bootstrap that tried to download from `oneget.org` and failed TLS trust).
- State at `C:\certs\_acme\config` (POSHACME_HOME set at Machine scope). Encrypted plugin args bound to SYSTEM, so setup and daily renewal both run as SYSTEM.
- Account: LE production, contact `mailto:dihank777@gmail.com`, account id `3272068881`.
- Plugin: `Cloudflare` with the scoped `vault_cloudflare_api_token` (from the vault).
- Two orders tracked:
  - `mondaynightracing.co.za` + `*.mondaynightracing.co.za`
  - `timing.mondaynightracing.co.za`
- Scheduled Task `AcmeRenew`, `03:15` daily, `SYSTEM`, `HIGHEST` privilege. Runs `C:\certs\_acme\renew.ps1`.
- `renew.ps1` calls `Submit-Renewal` (respects the 30-day window), and for any cert it gets back: copies `FullChainFile` + `KeyFile` over the deployed paths that httpd-vhosts.conf references, then `Restart-Service Apache2.4`. Logs to `C:\certs\_acme\renew.log` with ISO timestamps.
- Canonical scripts committed at `scripts/posh-acme-setup.ps1` (one-off, takes `-CFToken`) and `scripts/posh-acme-renew.ps1`.

**Recovery from lost state** (reimage, disk failure): upload `posh-acme-setup.ps1` to `C:\Windows\Temp`, create a one-shot scheduled task running it as SYSTEM with `-CFToken <vault value>`, run it, watch the log. Then re-register the `AcmeRenew` daily task. Whole recovery takes ~10 min.

### 2026-04-24 renewal round

All three deployed certs were expired. Process:

1. `acme.sh --issue --dns` with manual mode → printed TXT challenges.
2. Added TXT records at `_acme-challenge.<name>` in the Afrihost DNS panel.
3. `acme.sh --renew --dns` once TXT was consistent across all four authoritative NS.
4. Uploaded fullchain + key via WinRM into the same paths the vhosts already referenced (chunked base64 — pywinrm caps a single `run_ps` script at ~3000 chars).
5. `httpd.exe -t` to verify, `Restart-Service Apache2.4`.
6. Pre-deploy copies saved alongside originals as `*.bak-<timestamp>`.

Results:

| Cert | Status | New expiry | Issuer |
|---|---|---|---|
| `timing.mondaynightracing.co.za` | ✅ Deployed | 2026-07-23 | LE E8 |
| `mondaynightracing.co.za` + `*.mondaynightracing.co.za` | ✅ Deployed (after CF DNS migration) | 2026-07-23 | LE E7 |

> These 2026-04-24 issues expired 2026-07-23. Posh-ACME auto-renewed both on 2026-06-23 (now valid to **2026-09-21**), but a deploy bug meant the fresh PEMs weren't served until manually deployed during the 2026-07-24 fix (see the incident note under **Certificates** above). `dev.rablab.co.za` was removed 2026-07-24 and is no longer issued.

The wildcard was the holdout — manual-mode DNS-01 kept failing against Afrihost because their authoritative NS IPs were serving inconsistent zone content. Resolved by migrating the zone to Cloudflare and re-issuing with the `dns_cf` plugin (fully automated). Full story in `dns-cloudflare-migration.md`.

### Afrihost DNS gotcha → DNS migration to Cloudflare

`mondaynightracing.co.za` was on Afrihost NS: `ns.dns1.co.za`, `ns.dns2.co.za`, `ns.otherdns.net`, `ns.otherdns.com`. Each of those names resolves to two IPs, and the 8 IP endpoints served inconsistent zone content — half had our new `_acme-challenge` TXT, half didn't. LE's multi-vantage validation picks NS at random and any miss fails the renewal. Dead end.

Moved DNS hosting to **Cloudflare** (free plan). Registrar stays at Afrihost. Zone is imported, proxy is off, NS cutover is in progress — see `dns-cloudflare-migration.md` for the full state and procedure.

Once the zone is fully delegated to CF, we switch acme.sh from manual DNS mode to the `dns_cf` plugin using the API token stored in the vault (`vault_cloudflare_api_token`). Future renewals become fully unattended.

**Debugging tip for any Afrihost zone**: querying authoritative via *name* (`dig @ns.dns1.co.za.`) can surface cached answers; querying by **IP** (`dig @13.245.235.13`) bypasses that and shows true zone content. Also: each NS name has multiple IPs — iterate over them to find partial-sync issues.

## Ansible control

See `../ansible/`. `ansible windows -m win_ping` should return `pong`. Vars reference:
- `mnr_race_winrm_user` / `mnr_race_winrm_password` — from the encrypted vault.
- `sites[*]` — the cert/key paths above, for writing renewal playbooks against.
