#!/usr/bin/env bash
# Query the MNR Server Manager Web API (ACC or AC EVO). See docs/server-manager-api.md.
#
#   scripts/osm-api.sh acevo /healthcheck.json
#   scripts/osm-api.sh acevo /api/championship/list.json
#   scripts/osm-api.sh acc   '/api/results/list.json?page=0&sort=date'
#
# Logs in on demand and caches the session cookie in $TMPDIR, so repeat calls cost one request.
# The password is read from the ansible vault (vault_osm_admin_password) and passed to curl via
# a file, so it never lands in the process list or your shell history.
set -euo pipefail

HOST_KEY="${1:-}"
ENDPOINT="${2:-}"
if [[ -z "$HOST_KEY" || -z "$ENDPOINT" ]]; then
    sed -n '2,9p' "$0" | sed 's/^# \?//'
    exit 2
fi

case "$HOST_KEY" in
    acevo|acc) HOST="${HOST_KEY}.mondaynightracing.co.za" ;;
    *)         HOST="$HOST_KEY" ;;   # allow a full hostname
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="${TMPDIR:-/tmp}/osm-api-${HOST}.jar"
PWFILE=""
# Must return 0: this runs on EXIT, so a falsy last command would become the exit status.
cleanup() { [[ -n "$PWFILE" ]] && rm -f "$PWFILE"; return 0; }
trap cleanup EXIT

login() {
    PWFILE="$(mktemp)"; chmod 600 "$PWFILE"
    # Pull the password out of the vault without ever echoing it. The file holds ONLY the
    # value: curl's "Name@file" form urlencodes the file contents as the value of Name.
    # (Writing "Password=..." into the file and using "@file" would encode the '=' too.)
    printf '%s' "$(
        cd "$REPO_ROOT/ansible" &&
        ansible-vault view group_vars/all/vault.yml |
            sed -n 's/^vault_osm_admin_password: *"\?\([^"]*\)"\?$/\1/p'
    )" > "$PWFILE"
    if [[ ! -s "$PWFILE" ]]; then
        echo "osm-api: could not read vault_osm_admin_password from the vault" >&2
        exit 1
    fi
    curl -sS -c "$JAR" -o /dev/null -X POST \
        --data-urlencode "Username=admin" --data-urlencode "Password@$PWFILE" \
        "https://${HOST}/login"
    cleanup; PWFILE=""
}

fetch() { curl -sS ${1:+-b "$JAR"} -w '\n%{http_code}' "https://${HOST}${ENDPOINT}"; }

# /healthcheck.json is public — don't spend a login (or a rate-limit slot) on it.
if [[ "$ENDPOINT" == /healthcheck.json* ]]; then
    RESP="$(fetch)"
else
    [[ -f "$JAR" ]] || login
    RESP="$(fetch 1)"
    CODE="${RESP##*$'\n'}"
    # 302 here is ambiguous: expired session OR the 5-req/20s rate limiter. Retry a login once;
    # if it still redirects, it was the rate limiter.
    if [[ "$CODE" == "302" ]]; then
        rm -f "$JAR"; login; RESP="$(fetch 1)"
    fi
fi

CODE="${RESP##*$'\n'}"
BODY="${RESP%$'\n'*}"

if [[ "$CODE" == "302" ]]; then
    echo "osm-api: HTTP 302 after re-login — almost certainly the rate limiter" >&2
    echo "         (5 requests / 20 seconds). Wait 20s and retry." >&2
    exit 1
fi
[[ "$CODE" == "200" ]] || { echo "osm-api: HTTP $CODE" >&2; echo "$BODY" >&2; exit 1; }

if command -v jq >/dev/null 2>&1; then echo "$BODY" | jq .; else echo "$BODY"; fi
