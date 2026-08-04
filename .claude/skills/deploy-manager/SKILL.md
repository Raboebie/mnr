---
name: deploy-manager
description: "Build and deploy the MNR Server Manager (mnr-manager: Kotlin/Spring backend + embedded React SPA) to mnr-race over WinRM/JH1-VPN via ansible. Use when asked to deploy, redeploy, ship, or push the manager / manager.mondaynightracing.co.za, or after changing backend/frontend code, NSSM env vars, or the manager vhost. Covers the code-only fast path, env/secret changes, Apache changes, and full-box deploys, plus every gotcha (jar-path override, when the service/start tags are needed, disruptive shared-Apache restart)."
trigger: /deploy-manager
---

# Deploy the MNR Server Manager

Ship `mnr-manager` (Kotlin/Spring WebFlux backend with the React SPA embedded in the boot jar)
to **mnr-race** (`10.104.0.10`). Runs as the NSSM service `mnr-manager` on `:8090`, reverse-proxied
by Apache at **manager.mondaynightracing.co.za**.

## Two repos, one control root

| | |
|---|---|
| **App / build** | `~/git/mnr/mnr-manager` — build the jar here |
| **Ops / ansible** | `~/git/fun/mnr/ansible` — run the playbook from here (inventory, vault, `ansible.cfg`) |

The playbook `deploy-manager.yml` is authored in the app repo (`deploy/deploy-manager.yml`) but
**runs from the ops repo**. A synced copy lives at `~/git/fun/mnr/ansible/deploy-manager.yml`.
If you edit the app-repo copy (or its `templates/`), re-sync before deploying:

```bash
diff ~/git/mnr/mnr-manager/deploy/deploy-manager.yml ~/git/fun/mnr/ansible/deploy-manager.yml   # IDENTICAL?
cp ~/git/mnr/mnr-manager/deploy/{deploy-manager.yml,templates/httpd-manager.conf.j2} ~/git/fun/mnr/ansible/...   # if it differs
```

## Preflight (always)

1. **VPN up** — mnr-race is only reachable through the JH1 tunnel. Verify:
   ```bash
   cd ~/git/fun/mnr/ansible && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible windows -m win_ping
   ```
   Expect `pong`. If not, bring the tunnel up first (see project CLAUDE.md → "Reaching the server").
2. **macOS fork guard** — every ansible invocation needs `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`
   or it crashes with an objc fork error. All commands below include it.
3. **Vault intact** — the `service` tag pulls secrets from `group_vars/all/vault.yml`
   (`ansible.cfg` already points at `.vault_password`, no `--ask-vault-pass`). Only relevant when
   the `service` tag runs.

## Build the jar

The SPA is embedded into the jar (`processResources.dependsOn(buildWeb)`; `buildWeb` = `npm ci && npm run build`).

```bash
cd ~/git/mnr/mnr-manager
npm --prefix web run build                 # writes fresh static into backend/src/main/resources/static/
./gradlew :backend:bootJar                 # -> backend/build/libs/backend.jar (~45 MB, SPA inside)
```

**Gotcha — stale static:** `processResources` can report `UP-TO-DATE` and bundle an old SPA. Build the
web assets first (above), then **verify** the jar actually carries the current bundle:

```bash
# hash Vite emitted this build (npm run build writes here):
ls backend/src/main/resources/static/assets/index-*.js
# confirm the SAME index-*.js hash is inside the jar:
unzip -l backend/build/libs/backend.jar | grep -E 'static/assets/index-.*\.js'
```

The two must reference the same `index-<hash>.js`. If they differ, the jar is stale — rebuild.

> Do **not** run a backgrounded `:backend:test` (which triggers `buildWeb` → `npm ci`, wiping
> `node_modules`) concurrently with `npm run build`, or you get a transient `tsc: command not found`.

## Choose the deploy path

Match the smallest path to what actually changed:

| What changed | Tags / commands | Disruptive? |
|---|---|---|
| **Backend or frontend code only** (the common case) | `--tags artifacts` + jar override, then restart the service directly | No |
| **NSSM env var or a secret** (AppEnvironmentExtra: new password, Discord/Steam key, port…) | `--tags service` (needs svc creds) then restart the service | No (Apache untouched) |
| **Manager vhost / Apache** (`templates/httpd-manager.conf.j2`, proxy, cert path) | `--tags apache` then a graceful Apache reload | **Yes** — shared httpd |
| **Fresh box / first deploy** | full `ansible-playbook … ` (all tags in order) | Yes |

Tag dependency order (never skip predecessors on a fresh box): `dirs → jre → artifacts → acc → apache → service → start`.

### Two hard gotchas that bite every time

- **`manager_src_jar` default points at another machine** (`/home/dihan/...`). On this Mac you
  **must** override it: `-e manager_src_jar=/Users/dihankapp/git/mnr/mnr-manager/backend/build/libs/backend.jar`.
- **`service` tag requires run-as creds** — it asserts `svc_user`/`svc_password` and aborts without
  them. Pass `-e svc_user='MNR-RACE\MNR' -e svc_password='<MNR account / WinRM password>'`
  (the same Windows password used for WinRM; it lives in the vault, never in the repo — never echo it).
  So `--tags artifacts,service` fails on `service` unless you supply those. For a **code-only** push,
  don't run `service` at all — just swap the jar and restart (below).
- **`start` tag is the only disruptive one** — its `win_service restart` + `httpd -k restart` bounces
  the **single shared `httpd.exe`**, blipping every vhost (acc/ams2/timing/mnr/palace). For a code-only
  jar swap you don't need it: a direct `Restart-Service mnr-manager` reloads the jar and touches nothing else.

## The common case — code-only redeploy

```bash
cd ~/git/fun/mnr/ansible
JAR=/Users/dihankapp/git/mnr/mnr-manager/backend/build/libs/backend.jar

# 1. copy the new jar (non-disruptive)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  ansible-playbook deploy-manager.yml --tags artifacts -e manager_src_jar=$JAR

# 2. restart just the manager service (does NOT touch Apache)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  ansible windows -m win_shell -a "Restart-Service mnr-manager; Start-Sleep -Seconds 4; (Get-Service mnr-manager).Status"
```

Expect `Running`.

## Env-var / secret change

Same as above but also reconfigure NSSM (needs creds), then restart:

```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  ansible-playbook deploy-manager.yml --tags artifacts,service \
    -e manager_src_jar=$JAR \
    -e svc_user='MNR-RACE\MNR' -e svc_password='<vault: MNR account password>'
# then restart the service (step 2 above)
```

## Verify live (do this every deploy)

```bash
# served index.html references the bundle you just built:
curl -s https://manager.mondaynightracing.co.za/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'
# SPA deep-link falls through to index (200):
curl -s -o /dev/null -w '%{http_code}\n' https://manager.mondaynightracing.co.za/servers
# API is up and auth-gated (401), and endpoints are wired (401, not 405):
curl -s -o /dev/null -w '%{http_code}\n' https://manager.mondaynightracing.co.za/api/servers
```

The grepped bundle hash must equal the `index-<hash>.js` you built and verified inside the jar. If the
served hash is old, the jar was stale or the service didn't restart — recheck the build-verify step and
that `Restart-Service` returned `Running`.

## Commit & push first

Follow the superpowers flow before deploying: branch → commit → `merge --no-ff` to `master` → push
in the `mnr-manager` repo, then build + deploy the jar from `master`.
