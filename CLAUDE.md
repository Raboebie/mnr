# Repo orientation

This repo is ops glue for the **Monday Night Racing** Windows server (`mnr-race`, `10.104.0.10`) and related rablab-hosted domains. There is no application code here — it's infrastructure, docs, and Ansible.

## Layout

```
ansible/           Ansible control root (run commands from here)
  ansible.cfg
  inventory.yml
  group_vars/all/
    vars.yml       public vars (server paths, site list, VPN info)
    vault.yml      ansible-vault encrypted secrets (winrm creds, etc.)
  .vault_password  random password for the vault (gitignored)
docs/
  mnr-server.md    findings: host, Apache vhost map, certs, gotchas
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
- Renewal flow is **out-of-band via `acme.sh` in DNS-01 manual mode** on a workstation, then copy the PEMs up. The server's own Certbot install (v1.13.0, 2021) is dead — ignore it.
- For wildcard (`*.mondaynightracing.co.za`) DNS-01 is mandatory. Afrihost hosts the zone; TXT records go under `_acme-challenge`.
- LE validator caches TXT for the record TTL. Afrihost's default is 14400s (4h) — if a renewal fails with `Incorrect TXT record`, wait the TTL before retrying with new tokens. Apex validation is remembered per-account for 30d, so wildcard re-issues only need **one** new TXT value.
- Full context and the specific gotchas hit during the 2026-04-24 round are in `docs/mnr-server.md`.

## Uploading files via WinRM

`pywinrm`'s `run_ps` caps a single script at ~3000 characters. For binary uploads (certs, keys), base64-encode locally and append in chunks of ~2500 chars to a staging `.b64` file on the server, then decode with `[Convert]::FromBase64String` + `[IO.File]::WriteAllBytes`. There is a reference implementation in the git history under the 2026-04-24 cert deploy.

## Things to be careful about

- **Do not touch `C:\Apache24\conf\api.conf` or `extra\httpd-mnr.conf`** on the server — they are orphaned (not included by `httpd.conf`) but editing them gives a false sense of effect. Live vhosts are only in `extra\httpd-vhosts.conf`.
- `httpd-ssl.conf` is intentionally empty; SSL globals are configured per-vhost.
- `C:\Certbot\csr\` and `keys\` have ~120 leftover files from a broken 2021 auto-renew loop. Harmless but visually noisy.
- The `mnr` account works over WinRM only because `LocalAccountTokenFilterPolicy=1` is set in the registry. If someone wipes that key, remote auth starts failing with `InvalidCredentialsError` despite correct creds.
