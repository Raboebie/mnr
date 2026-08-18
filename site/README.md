# `site/`

`mnr_website/` is the source of truth for the **`mondaynightracing.co.za`** landing page, served from
`C:\mnr_website` on `mnr-race`. Snapshotted out of the live server 2026-08-18 — before
that, the only copy of this site was the server itself.

Deploy with `ansible/deploy-mnr-website.yml` (`--tags site`, non-disruptive). Edit here,
not on the box: the next deploy overwrites hand-edits.

| File | Notes |
|---|---|
| `index.html` | The whole page. Tailwind Play CDN + Lucide + Inter, all hotlinked. **CRLF line endings** — preserved via `.gitattributes`. |
| `image.png` | MNR logo in the header. |
| `favicon.png` | Byte-identical to `image.png` (same SHA-256). |
| `tracker.php` | Toy visit/click counter, writes `stats.txt`. |

`stats.txt` is **runtime state and is not in this repo**. The playbook copies files in
without deleting, so the live counter survives a deploy.
