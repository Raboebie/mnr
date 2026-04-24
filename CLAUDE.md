# Repo orientation

This repo is ops glue for the **Monday Night Racing** Windows server (`mnr-race`, `10.104.0.10`) and related rablab-hosted domains. There is no application code here — it's infrastructure, docs, and Ansible.

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
  website-c-website.md           dev.rablab.co.za DocumentRoot inventory
  website-c-mnr_website.md       mondaynightracing.co.za DocumentRoot inventory
  dns-cloudflare-migration.md    mnr.co.za DNS migration state and procedure
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
- DNS hosts are split:
  - `rablab.co.za` → still on Afrihost DNS. Manual DNS-01 mode. Afrihost's 14400s TTL means LE's validator cache can persist up to 4h after a failed attempt.
  - `mondaynightracing.co.za` → on Cloudflare (migrated 2026-04-24). Renew with `acme.sh --renew --dns dns_cf -d mondaynightracing.co.za -d '*.mondaynightracing.co.za'`. Token is in `vault_cloudflare_api_token` and already persisted in `~/.acme.sh/account.conf` after the first issue. Takes ~10 seconds, fully unattended. See `docs/dns-cloudflare-migration.md`.
- **Cron and a WinRM deploy hook are not yet wired up** — cert renewal and deploy to `mnr-race` is still a manual two-step. Next milestone is `scripts/deploy-cert-to-mnr-race.py` driven by acme.sh `--deploy-hook`, plus `acme.sh --install-cronjob`.
- LE remembers apex validations per-account for 30 days, so wildcard re-issues only need the wildcard TXT after the first successful apex validation.
- Full context (and the 2026-04-24 renewal round) is in `docs/mnr-server.md`.

## Uploading files via WinRM

`pywinrm`'s `run_ps` caps a single script at ~3000 characters. For binary uploads (certs, keys), base64-encode locally and append in chunks of ~2500 chars to a staging `.b64` file on the server, then decode with `[Convert]::FromBase64String` + `[IO.File]::WriteAllBytes`. There is a reference implementation in the git history under the 2026-04-24 cert deploy.

## Things to be careful about

- **Do not touch `C:\Apache24\conf\api.conf` or `extra\httpd-mnr.conf`** on the server — they are orphaned (not included by `httpd.conf`) but editing them gives a false sense of effect. Live vhosts are only in `extra\httpd-vhosts.conf`.
- `httpd-ssl.conf` is intentionally empty; SSL globals are configured per-vhost.
- `C:\Certbot\csr\` and `keys\` have ~120 leftover files from a broken 2021 auto-renew loop. Harmless but visually noisy.
- The `mnr` account works over WinRM only because `LocalAccountTokenFilterPolicy=1` is set in the registry. If someone wipes that key, remote auth starts failing with `InvalidCredentialsError` despite correct creds.
