# DNS migration: `mondaynightracing.co.za` → Cloudflare

Started 2026-04-24 after a week of Afrihost's authoritative NS servers returning inconsistent results between their 8 IP endpoints (2 IPs per name × 4 NS names), which kept blocking Let's Encrypt DNS-01 validation for the wildcard cert.

## Why Cloudflare

- Free plan covers everything we need: anycast authoritative DNS, unlimited records and queries, DNSSEC.
- Proper API → acme.sh `dns_cf` plugin handles wildcard renewals with zero manual TXT edits.
- Registrar stays at Afrihost; only DNS hosting moves. Registrar fees don't change.

`rablab.co.za` stays on its current DNS for now (cert is renewed through 2026-07-23, not urgent). If it hits the same Afrihost problem later, migrate it the same way.

## Current state (2026-04-24 — migration complete)

| | |
|---|---|
| CF zone status | **Active** |
| CF zone ID | `4ee0f0f1834407a3c90ac3f8de9b7e36` |
| CF account ID | `8daa5d05c975df852dc7cb6ed15076ad` |
| Delegated NS | `johnny.ns.cloudflare.com`, `miki.ns.cloudflare.com` |
| Records live | 20 (A×11, CNAME×2, MX×1, TXT×3, SRV×3) |
| Proxy status | All records grey (DNS only) — **do not enable proxy** without a deliberate reason |
| Wildcard cert | renewed via `dns_cf` the same day; valid through 2026-07-23 |

Recursive resolvers (`1.1.1.1`, `8.8.8.8`, `9.9.9.9`) see only the CF NS pair. Old Afrihost NS servers still serve stale zone data if queried directly, but nothing follows them any more because the parent delegation has flipped.

## Gotchas encountered

- **Afrihost requires 4 NS entries at the apex**, but Cloudflare only provides 2. Workaround options (in order of preference): ask Afrihost support via WhatsApp to relax the minimum, or duplicate the two CF NS to fill the 4 slots.
- **Afrihost has a 4-hour lock between NS edits.** Plan the cutover knowing this — if you change one NS and realise the rest are wrong, you wait.
- **Afrihost's zone export produced malformed SRV records** (missing the priority field) and a duplicate apex A record. The cleaned, CF-ready version is committed at `dns/mondaynightracing.co.za.zone`.
- **`_acme-challenge` TXT was intentionally excluded** from the import — acme.sh manages it during renewals; keeping a stale token around just confuses things.
- **Don't turn on the orange cloud (Cloudflare proxy) during the cutover.** Proxying routes HTTPS through CF's edge, which changes cert handling, breaks non-web services like cpanel/webmail/ftp/mail, and complicates ACME. Leaving all records grey gives a clean like-for-like migration. Proxy can be re-evaluated per-hostname later (public web properties only).

## Verifying consistency during the cutover

```bash
for r in '' www. timing. acc. ams2. files. mail. cpanel. webmail. ftp.; do
  cf=$(dig A "${r}mondaynightracing.co.za" @johnny.ns.cloudflare.com +short)
  af=$(dig A "${r}mondaynightracing.co.za" @ns.otherdns.net. +short)
  [ "$cf" = "$af" ] && echo "OK  ${r}mondaynightracing.co.za  $cf" || echo "DIFF ${r}  CF=$cf  AF=$af"
done
```

Any DIFF output is a problem to fix before the NS cutover completes.

## How the cutover went

1. Changed one Afrihost NS slot → hit the 4-hour lock before the other three could be updated. Afrihost support removed the lock on request.
2. Swapped the remaining 3 NS — Afrihost's UI required 4 entries, so the CF pair was duplicated. DNS tolerated that fine.
3. Cloudflare detected the delegation flip and marked the zone **Active** within minutes.
4. Ran `acme.sh --issue --dns dns_cf` with the scoped token — wildcard cert issued in ~10 seconds (TXT added via CF API, LE validated, TXT removed). Deployed to `C:\certs\mondaynightracing.co.za\*` via WinRM and `Restart-Service Apache2.4`.

## Automated renewals

acme.sh's `dns_cf` plugin reads `CF_Token` from the environment (or from `~/.acme.sh/account.conf` once persisted). Renewal is a one-liner:

```bash
export CF_Token="$(cd /home/dihan/git/mnr/mnr/ansible && ansible-vault view group_vars/all/vault.yml | awk '/^vault_cloudflare_api_token:/{print $2}')"
~/.acme.sh/acme.sh --renew --dns dns_cf \
  -d mondaynightracing.co.za -d '*.mondaynightracing.co.za'
```

After the first successful `--issue`, acme.sh persists `CF_Token` into `~/.acme.sh/account.conf`, so subsequent `--renew` calls don't need the env export. If you rotate the token, re-export and re-issue once to overwrite.

### Server-side automation now owns MNR renewals

The workstation-side acme.sh flow proved the end-to-end path on 2026-04-24. Same day, we moved renewal responsibility to the server itself using **Posh-ACME** — see `mnr-server.md` for the full writeup. The canonical scripts are in `scripts/posh-acme-*.ps1`. `dev.rablab.co.za` stays on the workstation-based flow until its DNS also moves to Cloudflare.
