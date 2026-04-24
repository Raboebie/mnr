# `C:\mnr_website`

DocumentRoot for the **`mondaynightracing.co.za`** Apache vhost on `mnr-race`. Serves a single-page landing for the MNR South African sim-racing community.

## Contents

```
C:\mnr_website\
├── index.html      6725 B   MNR landing page (Tailwind CSS, Lucide icons)
├── image.png      45666 B   MNR logo, rendered in the header (<img src="image.png">)
├── favicon.png    45666 B   byte-identical to image.png (same SHA-256)
├── tracker.php      786 B   toy visit/click counter, writes to stats.txt
└── stats.txt         30 B   plain-text counter file, e.g. "Visits: 673\nDiscord Clicks: 13"
```

Total: 5 files, ~90 KB. No subdirectories, no `.htaccess`.

## Serving

Vhost: `mondaynightracing.co.za:443` in `C:\Apache24\conf\extra\httpd-vhosts.conf`. Rewrite logic is SPA-style:

```
# Serve real files/dirs directly
RewriteCond %{DOCUMENT_ROOT}%{REQUEST_URI} -f [OR]
RewriteCond %{DOCUMENT_ROOT}%{REQUEST_URI} -d
RewriteRule ^ - [L]
# Anything else → /index.html (internal rewrite, URL preserved, 200 OK — not a 302)
RewriteRule ^ /index.html [L]
```

Verified externally:

| Path | Status | Size | Notes |
|---|---|---|---|
| `/` | 200 | 6725 | `index.html` |
| `/image.png` | 200 | 45666 | direct |
| `/stats.txt` | 200 | 30 | **publicly readable** — minor info leak |
| `/tracker.php?action=visit` | 200 | 7 | returns `Success`, bumps counter |
| `/does/not/exist` | 200 | 6725 | internal rewrite to `/index.html` |

PHP is wired up in `httpd.conf` via `LoadModule php_module "C:/php/php8apache2_4.dll"` + `AddType application/x-httpd-php .php`.

## Landing page (`index.html`)

Vanilla HTML with:

- **Tailwind CSS** from the **Play CDN** (`https://cdn.tailwindcss.com`) — the JIT runtime. Tailwind explicitly warns this is for prototyping, not production.
- **Lucide icons** from `unpkg.com` (inline `<i data-lucide>` elements hydrated by `lucide.createIcons()`).
- **Inter font** from Google Fonts.

Sections:

1. Header with "South African Sim Racing Community" pill and the MNR logo.
2. Two tile cards (glass/blur style), each with a background image hotlinked from Unsplash:
   - **Assetto Corsa Competizione** → links to `https://acc.mondaynightracing.co.za`.
   - **Automobilista 2** → links to `https://ams2.mondaynightracing.co.za`.
3. Tagline: *"Have fun, race fair, and see you on track!"*.
4. Discord CTA button → invite `https://discord.gg/E8dR97ffFy`.
5. Footer: four-colour SA flag-ish stripe + `© 2026 Monday Night Racing • South Africa`.

Two inline scripts at the bottom:

```js
lucide.createIcons();

// Hit the tracker on page load…
fetch('tracker.php?action=visit');

// …and when the Discord button is clicked
document.getElementById('discord-join-btn')
  .addEventListener('click', () => fetch('tracker.php?action=click'));
```

## Tracker (`tracker.php`)

```php
$logFile = 'stats.txt';
if (!file_exists($logFile)) {
    file_put_contents($logFile, "Visits: 0\nDiscord Clicks: 0");
}
$action = $_GET['action'] ?? '';
if ($action === 'visit' || $action === 'click') {
    $content = file_get_contents($logFile);
    preg_match('/Visits: (\d+)/', $content, $vMatch);
    preg_match('/Discord Clicks: (\d+)/', $content, $cMatch);
    $visits = (int)$vMatch[1];
    $clicks = (int)$cMatch[1];
    if ($action === 'visit') $visits++;
    if ($action === 'click') $clicks++;
    file_put_contents($logFile, "Visits: $visits\nDiscord Clicks: $clicks");
    echo "Success";
}
```

Quick-and-dirty. Notable properties:

- **No locking** — two concurrent `visit` requests can race and lose an increment.
- **No dedup / rate limit** — every page refresh is a "visit", trivially inflatable via repeated GETs (I bumped it by 3 during this indexing just by curling).
- **No auth** — anyone can call it.
- `stats.txt` is publicly readable via HTTP — anyone can see the counter values without running the PHP.
- Action whitelist is fine as-is; no SQL/eval, so risk surface is low.

## Things worth tidying (future)

- **Tailwind CDN → production build**. The Play CDN runtime is ~300 KB, runs on every page load, and Tailwind themselves advise against it in production. Move to a small build (PostCSS or the Tailwind CLI) and ship only the used classes. Big perf + reliability win.
- **De-dupe `favicon.png` and `image.png`** — they are byte-identical. Either reference `image.png` everywhere and drop `favicon.png`, or generate a small multi-resolution `favicon.ico` / smaller PNG set (current 45 KB favicon is excessive).
- **Self-host background images** — the two card backgrounds hotlink Unsplash. Fine for now, but breaks if Unsplash rotates URLs or blocks hotlinking.
- **Block `stats.txt` from the web**. Tiny info leak, trivial to close with a vhost rule:
  ```apache
  <Files "stats.txt">
      Require all denied
  </Files>
  ```
- **Replace the PHP tracker** with something less fragile if the numbers matter. Options:
  - SQLite via PHP PDO (gives you concurrency, timestamps, per-session dedup).
  - Plausible/Umami self-hosted analytics — richer data, one config.
  - Drop it entirely if the counts aren't watched.
- **Discord invite `discord.gg/E8dR97ffFy`** — verify it's set to never expire in the Discord server settings. A default invite link dies in 7 days.
- **Version control the site**. Right now the only record of these files is the live server; a change on disk is a change in production with no history. Moving the site into this repo (e.g. `website-mnr/`) and deploying via an Ansible playbook gives rollback + review.
- **Favicon size**. 45 KB for a favicon is heavy; shrink to a 16x16/32x32 PNG or proper `.ico`.
