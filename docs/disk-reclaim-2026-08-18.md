# Disk reclaim on mnr-race — 2026-08-18

`C:` had fallen to **2.23 GB free** of 49.4 GB (4.4 GB in July 2026). This records what was
removed, what was deliberately kept, and where to look first next time.

## Outcome

| Step | Reclaimed |
|---|---|
| Obsolete installers, staging dirs, Linux binaries | 530 MB |
| `ACEvo_Latest\`, AMS2 dedicated server, `C:\buzzworx` | 769 MB |
| Dormant Docker WSL data | **7 987 MB** |
| WinSxS component-store cleanup | still running at time of writing — see below |
| **Free before → after** | **2.23 GB → 11.37 GB** (excludes the WinSxS step) |

## The lesson: it was never the game servers

The obvious suspects — a duplicated 260 MB `content.kspkg`, two AC EVO installs — were real but
small. **87% of the reclaimed space was one dormant file**: `docker_data.vhdx`, 7.8 GB, last
modified **2024-10-29**. No Docker process, no Docker service, WSL distro `docker-desktop`
`Stopped`, `docker` CLI not even on PATH. It had been abandoned for ~22 months while the disk
filled up around it.

Next time `C:` gets tight, check for large dormant VM/container disks **before** auditing the
race-server folders:

```powershell
Get-ChildItem C:\Users\*\AppData\Local -Recurse -Include *.vhdx -EA SilentlyContinue |
  Sort-Object Length -Desc | Select-Object FullName,@{n='GB';e={[math]::Round($_.Length/1GB,2)}},LastWriteTime
```

Removed with `wsl --unregister docker-desktop`, then deleting the leftover
`C:\Users\MNR\AppData\Local\Docker`. Docker Desktop is still installed; starting it would
rebuild an empty VM. **Anything that was inside those container volumes is gone.**

## What was removed

**Installers and staging** — already installed, kept only as archives:

- `ACC server update packs\acc-server-manager_v1.4.2` + `.zip` (108 MB, dated 2025-06-13; the
  ACC manager is on v1.6.2)
- `ACEvoManager\acevo-server-manager_v1.6.3` + `.zip` (108 MB)
- the same pair again inside `ACEvoManager\_manager\servers\server_0\` (107 MB)

**Linux binaries on a Windows host** — `linux64\`, `steamclient.so`, `libsteamwebrtc.so`, in both
`ACEvoManager\` and its `server_0\` mirror (~190 MB).

> Why the duplicates: the EVO manager's `install_path` points at its **own** directory, so when
> it provisioned `server_0` it recursively copied the whole folder — including its own 40 MB
> manager binary, the installer zip, and the Linux builds — into the game-server instance dir.
> Expect this to come back after a manager upgrade or a server re-provision.

**Dead installs:**

- `ACEvo_Latest\` (483 MB) — the hand-launched AC EVO server. Superseded by `ACEvoManager\`;
  `ServerLauncher` was not running. Its `cars.json` / `events_practice.json` /
  `events_race_weekend.json` were verified **byte-identical** to the manager's copies and are
  snapshotted in `reference/acevo-config/`.
- `Automobilista 2 - Dedicated Server\` (184 MB) — AMS2 has no process, no service and no
  vhost of its own any more; the `ams2.` hostname serves the AC EVO manager.
- `C:\buzzworx` (101 MB, dated 2021) — matches the orphaned `api.buzzworx.co` vhost in
  `C:\Apache24\conf\api.conf`, which `httpd.conf` does not include. No IIS site, no service.

**WinSxS** — `Dism /Online /Cleanup-Image /StartComponentCleanup /ResetBase`. Windows itself
reported `Component Store Cleanup Recommended: Yes` with 2.52 GB in "Backups and Disabled
Features". `/ResetBase` means previously-installed Windows updates can no longer be uninstalled.

## What was deliberately kept

- **`C:\feedback` (110 MB) — DO NOT DELETE.** It reads as an abandoned 2025 ASP.NET app and its
  IIS site (`feedback.rablab.co.za`) is **Stopped**, but `C:\feedback\WebApi.exe` is running as
  a standalone process **listening on :8080**, up since 2026-05-11. It was on the delete list
  and was pulled off it one command short.
- **Edge stack** (~6.3 GB across `EdgeCore`, `Edge`, `EdgeWebView`) — WebView2 may be a
  dependency; not worth the risk.
- **`Copilot` (863 MB)**, `C:\Program Files\WSL` (649 MB) — plausible future candidates.
- Windows update caches were already clean (`SoftwareDistribution\Download` 1 MB,
  `Windows\Temp` 18 MB), and the ~120 stale Certbot `csr\`/`keys\` files that CLAUDE.md flags as
  noisy total **0.31 MB** — visually annoying, worthless to delete.

## Method

One-off commands over WinRM, each stage printing free space before and after, with guards:
`ACEvo_Latest` deletion aborted if any `ServerLauncher`/`AssettoCorsaEVOServer` process was
running, and both managers' `/healthcheck.json` were re-checked after the stage that removed
files from inside the live `ACEvoManager\` install (both stayed `OK`).
