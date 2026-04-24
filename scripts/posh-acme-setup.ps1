# One-time Posh-ACME setup on mnr-race.
#
# What it does (idempotent — safe to re-run if state is lost):
#   - creates C:\certs\_acme and sets POSHACME_HOME there (machine-wide)
#   - registers a Let's Encrypt production account for dihank777@gmail.com
#   - issues the two certs Posh-ACME will henceforth manage:
#       * mondaynightracing.co.za + *.mondaynightracing.co.za
#       * timing.mondaynightracing.co.za
#   - deploys fullchain + key into the paths httpd-vhosts.conf references
#   - restarts Apache2.4
#
# The Cloudflare API token is required for DNS-01 and is persisted
# DPAPI-encrypted inside Posh-ACME's state on first use. Subsequent
# renewals (via renew.ps1) do not need the plaintext token.
#
# Must run as SYSTEM (via a one-shot scheduled task) so the DPAPI
# encryption is bound to the same principal that runs the daily
# renewal task. Running as a regular user then switching to SYSTEM
# later breaks the stored token decryption.
#
# Usage (from an elevated shell on mnr-race):
#   schtasks /Create /TN PoshAcmeSetup /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Windows\Temp\posh-acme-setup.ps1 -CFToken cfut_XXXXX..." /SC ONCE /ST 23:59 /RU SYSTEM /RL HIGHEST /F
#   schtasks /Run /TN PoshAcmeSetup
#   Get-Content C:\Windows\Temp\posh-acme-setup.log -Wait

param(
    [Parameter(Mandatory = $true)]
    [string]$CFToken,
    [string]$AcmeContact = 'mailto:dihank777@gmail.com',
    [string]$AcmeHome = 'C:\certs\_acme\config'
)

$LogPath = 'C:\Windows\Temp\posh-acme-setup.log'
function L($msg) { "$(Get-Date -Format o) $msg" | Out-File -Append $LogPath -Encoding utf8 }

try {
    "START $(Get-Date -Format o)" | Out-File $LogPath -Encoding utf8

    if (-not (Test-Path $AcmeHome)) { New-Item -ItemType Directory -Force -Path $AcmeHome | Out-Null }
    $env:POSHACME_HOME = $AcmeHome
    [Environment]::SetEnvironmentVariable('POSHACME_HOME', $AcmeHome, 'Machine')
    L "POSHACME_HOME = $AcmeHome"

    Import-Module Posh-ACME
    Set-PAServer LE_PROD
    L "server: LE_PROD"

    $acct = Get-PAAccount -List 2>$null | Where-Object { $_.contact -contains $AcmeContact } | Select-Object -First 1
    if (-not $acct) {
        $acct = New-PAAccount -AcceptTOS -Contact $AcmeContact
        L "created account $($acct.id)"
    } else {
        Set-PAAccount -ID $acct.id
        L "using existing account $($acct.id)"
    }

    $cfArgs = @{ CFToken = (ConvertTo-SecureString $CFToken -AsPlainText -Force) }

    L "issuing mnr wildcard..."
    $mnrCert = New-PACertificate -Domain 'mondaynightracing.co.za','*.mondaynightracing.co.za' -Plugin Cloudflare -PluginArgs $cfArgs -AcceptTOS -Force
    L "mnr cert: $($mnrCert.FullChainFile)"

    L "issuing timing cert..."
    $timingCert = New-PACertificate -Domain 'timing.mondaynightracing.co.za' -Plugin Cloudflare -PluginArgs $cfArgs -AcceptTOS -Force
    L "timing cert: $($timingCert.FullChainFile)"

    foreach ($d in @('mondaynightracing.co.za','timing.mondaynightracing.co.za')) {
        if (-not (Test-Path "C:\certs\$d")) { New-Item -ItemType Directory -Force -Path "C:\certs\$d" | Out-Null }
    }

    Copy-Item -LiteralPath $mnrCert.FullChainFile -Destination 'C:\certs\mondaynightracing.co.za\fullchain.pem' -Force
    Copy-Item -LiteralPath $mnrCert.KeyFile -Destination 'C:\certs\mondaynightracing.co.za\privkey.pem' -Force
    L "deployed mnr wildcard"

    Copy-Item -LiteralPath $timingCert.FullChainFile -Destination 'C:\certs\timing.mondaynightracing.co.za\certificate.cer' -Force
    Copy-Item -LiteralPath $timingCert.KeyFile -Destination 'C:\certs\timing.mondaynightracing.co.za\private.key' -Force
    L "deployed timing"

    Restart-Service Apache2.4
    L "Apache2.4 restarted"

    "DONE $(Get-Date -Format o)" | Out-File -Append $LogPath -Encoding utf8
} catch {
    "ERROR: $_" | Out-File -Append $LogPath -Encoding utf8
    "DONE-ERROR $(Get-Date -Format o)" | Out-File -Append $LogPath -Encoding utf8
    exit 1
}
