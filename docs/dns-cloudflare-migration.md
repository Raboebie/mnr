# DNS migration: `mondaynightracing.co.za` → Cloudflare

Started 2026-04-24 after a week of Afrihost's authoritative NS servers returning inconsistent results between their 8 IP endpoints (2 IPs per name × 4 NS names), which kept blocking Let's Encrypt DNS-01 validation for the wildcard cert.

## Why Cloudflare

- Free plan covers everything we need: anycast authoritative DNS, unlimited records and queries, DNSSEC.
- Proper API → acme.sh `dns_cf` plugin handles wildcard renewals with zero manual TXT edits.
- Registrar stays at Afrihost; only DNS hosting moves. Registrar fees don't change.

`rablab.co.za` stays on its current DNS for now (cert is renewed through 2026-07-23, not urgent). If it hits the same Afrihost problem later, migrate it the same way.

## Current state (2026-04-24)

| | |
|---|---|
| CF zone status | Pending nameserver update |
| CF zone ID | `4ee0f0f1834407a3c90ac3f8de9b7e36` |
| CF account ID | `8daa5d05c975df852dc7cb6ed15076ad` |
| Assigned NS | `johnny.ns.cloudflare.com`, `miki.ns.cloudflare.com` |
| Records imported | 20 (A×11, CNAME×2, MX×1, TXT×3, SRV×3) |
| Proxy status | All records grey (DNS only) — **do not enable proxy** until we have a reason |
| NS cutover | 1 of 4 Afrihost NS slots changed to `johnny.ns.cloudflare.com`; remaining 3 locked behind Afrihost's 4-hour change window |

CF is already serving correct answers on `johnny.ns.cloudflare.com`. Because all 20 records match what Afrihost's nameservers return, the mixed delegation isn't causing user-visible breakage. DNS answers returned from CF match origin IPs exactly.

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

## Completing the cutover

1. Once Afrihost support or the 4-hour lock allows, change the remaining 3 NS slots:
   - Replace `ns.dns2.co.za`, `ns.otherdns.com`, `ns.otherdns.net` with `miki.ns.cloudflare.com` (and duplicates of `johnny.ns.cloudflare.com` / `miki.ns.cloudflare.com` if Afrihost insists on 4 distinct slots — DNS tolerates duplicates).
2. Cloudflare polls and flips the zone to **Active** — expect an email notification within 5–60 min of propagation.
3. Once active, the NS records inside CF's own zone become authoritative (they'll be `johnny.ns.cloudflare.com` and `miki.ns.cloudflare.com` — CF manages this).

## After the zone is Active: automate renewals

Switch acme.sh from manual DNS mode to the `dns_cf` plugin. The API token is already in the vault (`vault_cloudflare_api_token`, scoped `Zone.DNS:Edit + Zone.Zone:Read` on `mondaynightracing.co.za` only).

Rough procedure (once token is exported to the environment):

```bash
export CF_Token="$(ansible-vault view ansible/group_vars/all/vault.yml | awk '/^vault_cloudflare_api_token:/{print $2}')"
~/.acme.sh/acme.sh --issue --dns dns_cf \
  -d mondaynightracing.co.za -d '*.mondaynightracing.co.za' \
  --force
```

acme.sh will add the TXT, wait for propagation, validate, clean up — all unattended. Wire the renewal into cron once it's proven out.

## Registering the token for acme.sh

acme.sh's `dns_cf` plugin needs `CF_Token` (and optionally `CF_Account_ID`) set in its environment or saved into `~/.acme.sh/account.conf`. One-time setup:

```bash
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
# The --issue command with CF_Token in env will persist it into account.conf
```

Do this on the workstation that runs renewals (same machine where the vault lives). Don't copy the plaintext token into a shell-rc file — export it inline from the vault each session or have a wrapper script.
