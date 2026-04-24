# `C:\website`

DocumentRoot for two Apache vhosts on `mnr-race`:

- `dev.rablab.co.za` — serves the static content here.
- `timing.mondaynightracing.co.za` — declared with the same DocumentRoot but **proxies all traffic** to `http://10.104.0.10:8773/`, so the files here are never served for `timing.*` in practice.

As of 2026-04-24 this is effectively a **one-page privacy-policy site** for an app called *Tools4Nurds*.

## Contents

```
C:\website\
├── index.html                       4632 B   Tools4Nurds privacy policy page (Bootstrap 5 via CDN)
├── favicon.png                      2045 B
├── google9f6dc413840c26a0.html        53 B   Google Search Console verification file
├── files\
│   └── favicon.png                  2045 B   duplicate of the root favicon (no other assets referenced)
└── .well-known\
    └── acme-challenge\
        ├── web.config                665 B   IIS-style mime-map rule (ignored by Apache — leftover)
        └── index.html                  0 B   empty
```

Total: 6 files, ~10 KB.

## Live behaviour

External requests land through the `dev.rablab.co.za:443` vhost in `C:\Apache24\conf\extra\httpd-vhosts.conf`. The rewrite rules there matter more than the files on disk:

- `GET /` → **302** → `/index.html` (forced by `RewriteRule ^.*$ /index.html [L,R=302]` — every non-whitelisted path gets redirected here).
- `GET /favicon.png`, `/index.html`, `/files/*` — served as-is (whitelisted in the rewrite conditions).
- `POST /suggestions` → proxied to `http://10.104.0.10:8080/suggestions`.
- `POST /stats` → proxied to `http://10.104.0.10:8080/stats`.
- Anything else → 302 to `/index.html`. The backend at `:8080` appears to be offline (GET `/suggestions` returns 404), so the POST endpoints are currently untested.

The `.well-known/acme-challenge/` files are orphaned from an earlier HTTP-01 validation attempt — harmless but not used by anything now that we renew via DNS-01.

## Page details

`index.html` is a self-contained HTML page:

- Title: *Privacy Policy - Tools4Nurds*.
- Pulls Bootstrap 5.3.0 CSS from `cdn.jsdelivr.net` (no local CSS/JS bundles).
- Inline `<style>` for the container and footer; small inline `<script>` for the copyright year.
- Contact email listed: `dev.rablab@gmail.com`.
- Last-updated text in the page body: **February 2, 2025** (stale — file mtime is `2025-02-05`).

`google9f6dc413840c26a0.html` is the standard Google Search Console ownership token — leave it in place if the property is still registered.

## Things worth tidying (future)

- **Redundant 302 redirect at `/`**: Apache's default `DirectoryIndex index.html` already serves `/index.html` for `/`. The rewrite rule forcing an external 302 is unnecessary and adds a round-trip. Either remove that fallback rule or change it to an internal rewrite (no `R=` flag).
- **`.well-known/acme-challenge/` cleanup**: the IIS `web.config` and empty `index.html` serve no purpose here; delete.
- **Duplicate `favicon.png`**: `files/favicon.png` is identical to the root — pick one location, update any reference.
- **Update the "Last Updated" date** inside the policy text if/when the policy changes (currently hand-edited, not generated).
- **Backend status**: if `/suggestions` and `/stats` POST endpoints are meant to be live, stand up the `localhost:8080` service; otherwise remove those rewrite rules to avoid future confusion.
- **Content scope mismatch**: the domain is `dev.rablab.co.za` but the only page is a *Tools4Nurds* app privacy policy. Either add a proper landing page that links to the policy, or migrate the policy to a `/policies/tools4nurds.html` path so the domain root can serve something meaningful.
