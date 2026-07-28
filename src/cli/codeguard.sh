#!/usr/bin/env bash
#
# codeguard - scan a project's Python dependencies for known vulnerabilities.
#
# Exit codes (this is what makes it usable in CI):
#   0  scanned successfully, nothing found
#   1  vulnerabilities found
#   2  the scan could not complete - results are UNKNOWN, not clean
set -o pipefail

CODEGUARD_URL="${CODEGUARD_URL:-http://localhost:80}"
CODEGUARD_VERSION="2.1.0"
OUTPUT_JSON=0
WIDTH=74

# ---------------------------------------------------------------- presentation
# Colour only when writing to a terminal, and honour NO_COLOR. Piping to a file
# or a CI log must stay clean.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
    C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'
    C_CRIT=$'\033[1;31m'; C_HIGH=$'\033[1;33m'; C_MOD=$'\033[33m'
    C_LOW=$'\033[36m'; C_OK=$'\033[1;32m'; C_ERR=$'\033[1;31m'; C_ACCENT=$'\033[1;36m'
else
    C_RESET=""; C_DIM=""; C_BOLD=""
    C_CRIT=""; C_HIGH=""; C_MOD=""; C_LOW=""; C_OK=""; C_ERR=""; C_ACCENT=""
fi

# `tr` is byte-oriented and mangles multi-byte characters, so box drawing has
# to be built by repetition rather than by translating spaces.
repeat() {
    local char=$1 times=$2 out='' i
    for (( i = 0; i < times; i++ )); do out+="$char"; done
    printf '%s' "$out"
}

rule() { repeat "${1:-─}" "$WIDTH"; printf '\n'; }

header() {
    local title="codeguard v${CODEGUARD_VERSION}" bar
    bar=$(repeat '─' $((WIDTH - 2)))
    printf '\n%s╭%s╮%s\n' "$C_ACCENT" "$bar" "$C_RESET"
    # Padding is computed from the visible length: printf counts the colour
    # escapes as characters, so they must stay outside the padded field.
    printf '%s│%s %s%s%s%*s%s│%s\n' \
        "$C_ACCENT" "$C_RESET" "$C_BOLD" "$title" "$C_RESET" \
        $((WIDTH - 3 - ${#title})) '' "$C_ACCENT" "$C_RESET"
    printf '%s╰%s╯%s\n\n' "$C_ACCENT" "$bar" "$C_RESET"
}

severityColour() {
    case "$1" in
        CRITICAL) printf '%s' "$C_CRIT" ;;
        HIGH)     printf '%s' "$C_HIGH" ;;
        MODERATE|MEDIUM) printf '%s' "$C_MOD" ;;
        LOW)      printf '%s' "$C_LOW" ;;
        *)        printf '%s' "$C_DIM" ;;
    esac
}

message() {
    local colour=$1 text=$2
    header
    printf '  %s%s%s\n\n' "$colour" "$text" "$C_RESET"
}

spinnerStart() {
    [ -t 1 ] || return 0
    ( while :; do
        for frame in '|' '/' '-' '\'; do
            printf '\r  %s%s%s scanning %s...' "$C_ACCENT" "$frame" "$C_RESET" "$C_DIM"
            sleep 0.12
        done
      done ) 2>/dev/null &
    SPINNER_PID=$!
}

spinnerStop() {
    [ -n "${SPINNER_PID:-}" ] || return 0
    kill "$SPINNER_PID" 2>/dev/null
    wait "$SPINNER_PID" 2>/dev/null
    printf '\r\033[K%s' "$C_RESET"
    SPINNER_PID=""
}

# Renders the report. Reads a TSV from jq so that version comparison (which jq
# cannot do) happens in the shell with sort -V.
renderReport() {
    # Every variable is local: without this, `read` below would clobber the
    # caller's `count` through bash's dynamic scoping.
    local body=$1 scanned vulnerable node noun
    local severity package version count ids fixes colour best
    scanned=$(printf '%s' "$body" | jq -r '.scanned')
    vulnerable=$(printf '%s' "$body" | jq -r '.vulnerable')
    node=$(printf '%s' "$body" | jq -r '.node // "?"')
    noun=$([ "$scanned" = "1" ] && echo package || echo packages)

    header
    printf '  %s%s %s scanned%s  ·  %s%s vulnerable%s  %s· node %s%s\n\n' \
        "$C_BOLD" "$scanned" "$noun" "$C_RESET" \
        "$([ "$vulnerable" -gt 0 ] && printf '%s' "$C_ERR" || printf '%s' "$C_OK")" \
        "$vulnerable" "$C_RESET" "$C_DIM" "$node" "$C_RESET"

    while IFS=$'\t' read -r severity package version count ids fixes; do
        [ -z "$severity" ] && continue
        colour=$(severityColour "$severity")
        printf '  %s%-9s%s %s%s%s %s%s%s%*s%s%s advisor%s%s\n' \
            "$colour" "$severity" "$C_RESET" \
            "$C_BOLD" "$package" "$C_RESET" "$C_DIM" "$version" "$C_RESET" \
            $(( 34 - ${#package} - ${#version} > 0 ? 34 - ${#package} - ${#version} : 1 )) '' \
            "$C_DIM" "$count" "$([ "$count" = "1" ] && echo y || echo ies)" "$C_RESET"
        printf '            %s%s%s\n' "$C_DIM" "$ids" "$C_RESET"
        if [ -n "$fixes" ]; then
            # Highest fixed version = the one upgrade that clears everything.
            best=$(printf '%s' "$fixes" | tr ' ' '\n' | grep -v '^$' | sort -V | tail -1)
            printf '            %supgrade → %s%s%s\n' "$C_OK" "$C_BOLD" "$best" "$C_RESET"
        else
            printf '            %sno fixed version published%s\n' "$C_DIM" "$C_RESET"
        fi
        printf '\n'
    done < <(printf '%s' "$body" | jq -r '
        .findings[] |
        (.vulnerabilities | map(.cves[0] // .id) | unique) as $ids |
        [
            .max_severity,
            .package,
            (.version // "*"),
            (.vulnerability_count | tostring),
            # Three ids max: 12-space indent + 3 ids + " +N more" stays inside
            # the 74-column report. The full set is available via `codeguard -j`.
            (($ids[0:3] | join(", ")) +
             (if ($ids | length) > 3 then " +\($ids | length - 3) more" else "" end)),
            (.vulnerabilities | map(.fixed_in[]?) | unique | join(" "))
        ] | @tsv')

    local warnings
    warnings=$(printf '%s' "$body" | jq -r '.warnings[]?')
    if [ -n "$warnings" ]; then
        printf '%s' "$C_DIM"; rule '·'; printf '%s' "$C_RESET"
        printf '%s\n' "$warnings" | sed "s/^/  ${C_HIGH}!${C_RESET} /"
        printf '\n'
    fi
}

usage() {
    printf 'Usage: %s [-s <package>] [-j] [-u] [-v] [-h]\n' "$0" 1>&2
    exit 2
}

help() {
    header
    cat <<EOF
  ${C_BOLD}USAGE${C_RESET}
    codeguard                   Scan every dependency in this repository
    codeguard -s <package>      Scan one package, e.g. -s flask==2.2.2
    codeguard -j                Emit raw JSON (for pipelines)
    codeguard -u                Update the CLI to the latest release
    codeguard -v                Print the installed version
    codeguard -h                Show this help

  ${C_BOLD}EXIT CODES${C_RESET}
    ${C_OK}0${C_RESET}  clean          ${C_ERR}1${C_RESET}  vulnerabilities found     ${C_HIGH}2${C_RESET}  scan failed

  ${C_BOLD}ENVIRONMENT${C_RESET}
    CODEGUARD_URL               Server address (default http://localhost:80)
    NO_COLOR                    Disable coloured output

EOF
}

# Collects requirements WITHOUT touching the user's requirements.txt.
# The previous version ran \`pipreqs --force\`, which silently overwrote it.
collectRequirements() {
    local generated=""
    if command -v pipreqs >/dev/null 2>&1; then
        generated=$(pipreqs --print . 2>/dev/null)
    fi
    if [ -n "$generated" ]; then
        printf '%s\n' "$generated"
        return 0
    fi
    if [ -f requirements.txt ]; then
        cat requirements.txt
        return 0
    fi
    return 1
}

# Scans the given packages and reports the result. See exit codes above.
executeScanRequest() {
    local dependencies=("$@")
    if [ ${#dependencies[@]} -eq 0 ]; then
        message "$C_HIGH" "No dependencies to scan"
        return 2
    fi

    # mktemp, so a file called dep.json in the working directory is never clobbered.
    local body_file
    body_file=$(mktemp "${TMPDIR:-/tmp}/codeguard.XXXXXX") || return 2
    # shellcheck disable=SC2064
    trap "rm -f '$body_file'; spinnerStop" RETURN

    if ! printf '%s\n' "${dependencies[@]}" \
        | jq -R . | jq -s '{dependencies: .}' > "$body_file"; then
        message "$C_ERR" "Could not build the scan request"
        return 2
    fi

    [ "$OUTPUT_JSON" -eq 0 ] && spinnerStart
    local raw curl_rc http_status http_body
    raw=$(curl -sS --max-time 120 -w '\n%{http_code}' -X POST "$CODEGUARD_URL/scan" \
        -H 'Content-Type: application/json' --data-binary @"$body_file" 2>/dev/null)
    curl_rc=$?
    spinnerStop

    if [ $curl_rc -ne 0 ]; then
        message "$C_ERR" "Could not reach the codeguard server at $CODEGUARD_URL
  Results are UNKNOWN, not clean."
        return 2
    fi

    http_status="${raw##*$'\n'}"
    http_body="${raw%$'\n'*}"

    if [ "$http_status" != "200" ]; then
        local detail
        detail=$(printf '%s' "$http_body" | jq -r '.error // empty' 2>/dev/null)
        message "$C_ERR" "Scan failed - server returned HTTP $http_status
  ${detail:-no detail provided}
  Results are UNKNOWN, not clean."
        return 2
    fi

    local count
    count=$(printf '%s' "$http_body" | jq -r '.findings | length' 2>/dev/null)
    if [ -z "$count" ]; then
        message "$C_ERR" "Server returned an unreadable response. Results are UNKNOWN, not clean."
        return 2
    fi

    if [ "$OUTPUT_JSON" -eq 1 ]; then
        printf '%s\n' "$http_body" | jq .
    elif [ "$count" -gt 0 ]; then
        renderReport "$http_body"
    fi

    [ "$count" -eq 0 ] && return 0
    return 1
}

reportClean() {
    local subject=$1 scanned=${2:-}
    [ "$OUTPUT_JSON" -eq 1 ] && return 0
    message "$C_OK" "No known vulnerabilities in $subject${scanned:+ ($scanned scanned)}"
}

while getopts ":s:juhv" o; do
    case "${o}" in
        j)
            OUTPUT_JSON=1
            ;;
        s)
            executeScanRequest "${OPTARG}"
            scan_rc=$?
            [ $scan_rc -eq 0 ] && reportClean "${OPTARG}"
            exit $scan_rc
            ;;
        u)
            # Update to the latest release, verifying the archive against the
            # SHA256SUMS published with it. A security tool must not install
            # code it cannot verify, so a missing checksum file is a hard stop
            # rather than a warning.
            set -e
            repo="${CODEGUARD_REPO:-Naor-Yekutiely/codeguard}"
            workdir=$(mktemp -d "${TMPDIR:-/tmp}/codeguard-update.XXXXXX")
            trap 'rm -rf "$workdir"' EXIT

            release=$(curl -sS --fail --proto '=https' --tlsv1.2 \
                "https://api.github.com/repos/$repo/releases/latest")
            latest_tag=$(printf '%s' "$release" | jq -r '.tag_name')
            if ! [[ "$latest_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                printf 'Refusing to install unexpected release tag: %s\n' "'$latest_tag'" >&2
                exit 2
            fi
            if [ "$latest_tag" = "v$CODEGUARD_VERSION" ]; then
                printf 'Already on the latest release (%s)\n' "$latest_tag"
                exit 0
            fi

            sums_url=$(printf '%s' "$release" \
                | jq -r '.assets[]? | select(.name=="SHA256SUMS") | .browser_download_url')
            if [ -z "$sums_url" ] || [ "$sums_url" = "null" ]; then
                printf 'Release %s publishes no SHA256SUMS - refusing to install unverified code.\n' "$latest_tag" >&2
                printf 'Install manually from source if you trust it.\n' >&2
                exit 2
            fi

            tarball="codeguard-${latest_tag:1}.tar.gz"
            printf 'Fetching codeguard %s\n' "$latest_tag"
            curl -sS --fail --proto '=https' --tlsv1.2 -L \
                -o "$workdir/$tarball" \
                "https://github.com/$repo/archive/refs/tags/$latest_tag.tar.gz"
            curl -sS --fail --proto '=https' --tlsv1.2 -L -o "$workdir/SHA256SUMS" "$sums_url"

            expected=$(awk -v f="$tarball" '$2 == f || $2 == "*"f {print $1}' "$workdir/SHA256SUMS" | head -1)
            if [ -z "$expected" ]; then
                printf 'SHA256SUMS has no entry for %s - refusing to install.\n' "$tarball" >&2
                exit 2
            fi
            if command -v sha256sum >/dev/null 2>&1; then
                actual=$(sha256sum "$workdir/$tarball" | awk '{print $1}')
            else
                actual=$(shasum -a 256 "$workdir/$tarball" | awk '{print $1}')
            fi
            if [ "$expected" != "$actual" ]; then
                printf 'Checksum mismatch - refusing to install.\n  expected %s\n  actual   %s\n' \
                    "$expected" "$actual" >&2
                exit 2
            fi
            printf 'Checksum verified.\n'

            tar -xf "$workdir/$tarball" -C "$workdir"
            (cd "$workdir/codeguard-${latest_tag:1}/src/cli" && ./install_cli.sh)
            set +e
            ;;
        h)
            help
            ;;
        v)
            printf '%s\n' "$CODEGUARD_VERSION"
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

if [ $OPTIND -eq 1 ] || { [ "$OUTPUT_JSON" -eq 1 ] && [ $OPTIND -eq 2 ]; }; then
    # Full repository scan
    if [ ! -d .git ]; then
        message "$C_HIGH" "Not a git repository. Run codeguard inside one."
        exit 2
    fi

    requirements_arr=()
    while IFS= read -r line || [ -n "$line" ]; do
        [ -n "$line" ] && requirements_arr+=("$line")
    done < <(collectRequirements)

    if [ ${#requirements_arr[@]} -eq 0 ]; then
        message "$C_DIM" "No Python dependencies found in this repository."
        exit 0
    fi

    executeScanRequest "${requirements_arr[@]}"
    scan_rc=$?
    [ $scan_rc -eq 0 ] && reportClean "this repository" "${#requirements_arr[@]}"
    exit $scan_rc
fi
