# Daily renewal job for Posh-ACME-managed certs on mnr-race.
# Runs under SYSTEM via the 'AcmeRenew' scheduled task (03:15 daily).
# Submit-Renewal respects the 30-day renewal window by default, so
# most days this script logs "nothing to renew" and exits cleanly.
#
# Deploy paths match what C:\Apache24\conf\extra\httpd-vhosts.conf
# references. Update the $deployMap hashtable here if a vhost path
# ever changes, otherwise renewals will succeed but land in the wrong
# place and Apache will serve a stale cert.
#
# This file lives at C:\certs\_acme\renew.ps1 on the server.

$LogPath = 'C:\certs\_acme\renew.log'
function L($msg) { "$(Get-Date -Format o) $msg" | Out-File -Append $LogPath -Encoding utf8 }

$deployMap = @{
    'mondaynightracing.co.za' = @{
        fullchain = 'C:\certs\mondaynightracing.co.za\fullchain.pem'
        key       = 'C:\certs\mondaynightracing.co.za\privkey.pem'
    }
    'timing.mondaynightracing.co.za' = @{
        fullchain = 'C:\certs\timing.mondaynightracing.co.za\certificate.cer'
        key       = 'C:\certs\timing.mondaynightracing.co.za\private.key'
    }
}

try {
    L "=== renewal run START ==="
    $env:POSHACME_HOME = 'C:\certs\_acme\config'
    Import-Module Posh-ACME
    Set-PAServer LE_PROD | Out-Null

    $renewed = @(Submit-Renewal -AllAccounts -ErrorAction Continue)
    L "Submit-Renewal returned $($renewed.Count) renewed cert(s)"

    if ($renewed.Count -eq 0) {
        L "nothing to renew (all certs outside 30-day window)"
        return
    }

    foreach ($cert in $renewed) {
        # Submit-Renewal returns PACertificate objects, whose domain lives on
        # .Subject (CN=...), not .MainDomain. Deriving $dom from .MainDomain
        # alone yields $null and crashes ContainsKey($null) - which is exactly
        # what silently broke the 2026-06-23 renewal. Fall back to the CN.
        $dom = $cert.MainDomain
        if (-not $dom -and $cert.Subject) { $dom = ($cert.Subject -replace '^CN=', '').Trim() }
        if (-not $dom) {
            L "WARNING: could not determine domain for a renewed cert - skipping deploy"
            continue
        }
        if (-not $deployMap.ContainsKey($dom)) {
            L "WARNING: no deploy map entry for $dom - skipping deploy"
            continue
        }
        # The renewed object's file paths can be empty; Get-PACertificate is the
        # authoritative source for the on-disk fullchain/key.
        $pac = Get-PACertificate $dom
        $d = $deployMap[$dom]
        Copy-Item -LiteralPath $pac.FullChainFile -Destination $d.fullchain -Force
        Copy-Item -LiteralPath $pac.KeyFile       -Destination $d.key       -Force
        L "deployed $dom -> $($d.fullchain)"
    }

    # Validate config (this loads every cert+key pair) before restarting, so a
    # bad deploy logs an error and leaves the running Apache untouched rather
    # than taking every vhost down.
    & C:\Apache24\bin\httpd.exe -t 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        L "ERROR: httpd -t failed after deploy (exit $LASTEXITCODE) - NOT restarting Apache"
        L "=== renewal run END (error) ==="
        exit 1
    }
    Restart-Service Apache2.4
    L "Apache2.4 restarted after renewal"
    L "=== renewal run END (success) ==="
} catch {
    L "ERROR: $_"
    L "=== renewal run END (error) ==="
    exit 1
}
