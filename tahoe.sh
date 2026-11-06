#!/usr/bin/env bash
# macOS Tahoe Liquid Glass — all-in-one manager.
#
#   ./tahoe.sh                 interactive menu
#   ./tahoe.sh status          verify the live desktop + diagnostics
#   ./tahoe.sh install [profile]   install (full|lightweight|visual-only)
#   ./tahoe.sh dry-run [profile]   show every change without applying it
#   ./tahoe.sh resume          continue an interrupted installation
#   ./tahoe.sh repair          diagnose and re-apply managed components
#   ./tahoe.sh verify          live verification
#   ./tahoe.sh headless        verification + isolated nested GNOME Shell test
#   ./tahoe.sh capture         capture screenshots in the isolated Shell
#   ./tahoe.sh export          build the portable release
#   ./tahoe.sh restore [backup]    restore the pre-install desktop
#   ./tahoe.sh uninstall       remove owned components and restore settings
#   ./tahoe.sh logs            show logs/reports/diagnostics
#   ./tahoe.sh publish         create/update the GitHub repository and push
#   ./tahoe.sh menu            interactive menu
#
# GitHub publishing uses GITHUB_TOKEN (or GH_TOKEN) from the environment or
# ~/.bashrc. The token is never printed, written to the repo, or stored in the
# git remote URL.
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

readonly C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_DIM=$'\033[2m'
readonly C_RED=$'\033[1;31m' C_GREEN=$'\033[1;32m' C_BLUE=$'\033[1;34m' C_YELLOW=$'\033[1;33m'

say()  { printf '%s\n' "$*"; }
note() { printf '%s›%s %s\n' "$C_DIM" "$C_RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%sError:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
confirm() {
    local prompt="$1" answer
    read -r -p "$prompt [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

trap 'die "interrupted"' INT TERM
on_error() { printf '%sAction failed%s (exit %s, line %s). See logs/.\n' \
    "$C_RED" "$C_RESET" "$?" "$1" >&2; }
trap 'on_error $LINENO' ERR

require() {
    [[ -x "$ROOT/$1" ]] || die "missing executable: $1"
}

# ── operations ────────────────────────────────────────────────────────────
op_status() {
    note "live verification"
    "$ROOT/verify.sh" || warn "verification reported problems (see above)"
    note "diagnostics"
    "$ROOT/scripts/diagnostics.sh" || true
    say ""
    say "${C_BOLD}Latest state${C_RESET}"
    python3 - "$ROOT/state/installation.json" <<'PY' || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(f"  profile: {d.get('profile')}   phases: {len(d.get('completed_phases', []))}"
          f"   failed: {d.get('failed_phases', [])}   resume: {d.get('resume_required')}")
    print(f"  backup:  {d.get('pristine_backup') or d.get('backup_dir')}")
except Exception as exc:
    print(f"  (no state yet: {exc})")
PY
}

op_install() {
    local profile="${1:-}"
    require install.sh
    if [[ -z "$profile" ]]; then
        note "Choose a profile:"
        say "  1) auto (hardware recommendation)"
        say "  2) full (maximum effects)"
        say "  3) lightweight (recommended on Intel HD 4000)"
        say "  4) visual-only (themes/icons/wallpaper/fonts only)"
        read -r -p "Selection [1]: " choice
        case "${choice:-1}" in
            2) profile=full ;;
            3) profile=lightweight ;;
            4) profile=visual-only ;;
            *) profile="" ;;
        esac
    fi
    if [[ -n "$profile" ]]; then
        "$ROOT/install.sh" --profile "$profile"
    else
        "$ROOT/install.sh"
    fi
}

op_dryrun() {
    require install.sh
    local profile="${1:-}"
    if [[ -n "$profile" ]]; then
        "$ROOT/install.sh" --dry-run --profile "$profile"
    else
        "$ROOT/install.sh" --dry-run
    fi
}

op_resume()   { require install.sh;   "$ROOT/install.sh" --resume; }
op_repair()   { require repair.sh;    "$ROOT/repair.sh"; }
op_verify()   { require verify.sh;    "$ROOT/verify.sh"; }
op_headless() { require verify.sh;    "$ROOT/verify.sh" --headless; }
op_capture()  { python3 -E -s "$ROOT/tools/capture_visuals.py"; }
op_export()   { require export.sh;    "$ROOT/export.sh"; }

op_restore() {
    require install.sh
    local backup="${1:-}"
    warn "This restores the pre-install desktop configuration and removes project-owned files."
    confirm "Restore the original desktop?" || { say "Cancelled."; return 0; }
    if [[ -n "$backup" ]]; then
        "$ROOT/install.sh" --restore "$backup"
    else
        "$ROOT/install.sh" --restore
    fi
}

op_uninstall() {
    require uninstall.sh
    warn "This restores the original desktop and removes only project-owned components."
    confirm "Uninstall the macOS Tahoe customization?" || { say "Cancelled."; return 0; }
    "$ROOT/uninstall.sh" --yes
}

op_logs() {
    note "recent logs"
    ls -1t "$ROOT/logs"/*.log 2>/dev/null | head -8 || say "  (none)"
    say ""
    note "reports"
    find "$ROOT/docs/reports" -maxdepth 1 -name '*.md' 2>/dev/null | sort || true
    ls -1 "$ROOT/reports/verification.json" "$ROOT/reports/diagnostics.json" 2>/dev/null || true
    say ""
    note "tip: ./tahoe.sh status runs a fresh verification and diagnostics pass"
}

# ── GitHub publishing ─────────────────────────────────────────────────────
load_github_token() {
    local token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
    if [[ -z "$token" && -f "$HOME/.bashrc" ]]; then
        local line
        line="$(grep -E '^[[:space:]]*export[[:space:]]+(GITHUB_TOKEN|GH_TOKEN|GITHUB_PAT)=' \
            "$HOME/.bashrc" 2>/dev/null | tail -1 || true)"
        if [[ -n "$line" ]]; then
            # Evaluate only the export line; never print its value.
            eval "$line"
            token="${GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_PAT:-}}}"
        fi
    fi
    [[ -n "$token" ]] || die "no GitHub token found (set GITHUB_TOKEN or export it in ~/.bashrc)"
    printf '%s' "$token"
}

github_api() {
    # usage: github_api METHOD PATH [JSON_DATA]
    local method="$1" path="$2" data="${3:-}" token="$4"
    if [[ -n "$data" ]]; then
        curl -sS -X "$method" "https://api.github.com${path}" \
            -H "Authorization: Bearer ${token}" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            -d "$data"
    else
        curl -sS -X "$method" "https://api.github.com${path}" \
            -H "Authorization: Bearer ${token}" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28"
    fi
}

op_publish() {
    command -v git >/dev/null || die "git is required"
    command -v curl >/dev/null || die "curl is required"
    command -v jq >/dev/null || die "jq is required"

    local token user repo visibility private description
    token="$(load_github_token)"
    export GH_TOKEN="$token"

    user="$(github_api GET /user "" "$token" | jq -r '.login // empty')"
    [[ -n "$user" ]] || die "GitHub token is invalid or lacks access"

    repo="${REPO_NAME:-macos-tahoe-ubuntu}"
    if [[ -t 0 ]]; then
        read -r -p "Repository name [$repo]: " input
        repo="${input:-$repo}"
    fi
    [[ "$repo" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid repository name: $repo"

    visibility="${REPO_VISIBILITY:-private}"
    if [[ -t 0 ]]; then
        say "Visibility:"
        say "  1) private (recommended — includes desktop screenshots)"
        say "  2) public"
        read -r -p "Selection [1]: " choice
        case "${choice:-1}" in
            2) visibility=public ;;
            *) visibility=private ;;
        esac
    fi
    if [[ "$visibility" == "public" ]]; then
        private=false
    else
        private=true
    fi
    description="macOS Tahoe Liquid Glass desktop for Ubuntu GNOME with a reproducible installer"

    say "${C_BOLD}Publishing${C_RESET} ${user}/${repo} (${visibility})"

    # 1) local repository
    if [[ ! -d "$ROOT/.git" ]]; then
        git init -q -b main "$ROOT"
    fi
    git -C "$ROOT" config user.name >/dev/null 2>&1 || \
        git -C "$ROOT" config user.name "Michael Owusu Ntim"
    git -C "$ROOT" config user.email >/dev/null 2>&1 || \
        git -C "$ROOT" config user.email "${user}@users.noreply.github.com"

    # 2) stage, refusing proprietary/secret content
    git -C "$ROOT" add -A
    if git -C "$ROOT" diff --cached --name-only | grep -qE '(^|/)assets/(references|wallpapers/apple)/'; then
        git -C "$ROOT" reset >/dev/null
        die "refusing to publish proprietary Apple assets (excluded by .gitignore)"
    fi
    if git -C "$ROOT" diff --cached --name-only | grep -qE '(^|/)(\.env|secrets?|credentials)'; then
        git -C "$ROOT" reset >/dev/null
        die "refusing to publish potential secret files"
    fi
    # Split the pattern so this script's own source cannot match it.
    local secret_re
    secret_re='ghp''_[A-Za-z0-9]{20,}|github''_pat_[A-Za-z0-9_]{20,}|ANTHROPIC''_AUTH_TOKEN='
    if git -C "$ROOT" grep --cached -I -qE "$secret_re" || \
       git -C "$ROOT" grep --cached -I -qF "$token"; then
        git -C "$ROOT" reset >/dev/null
        die "refusing to publish: a token was found in staged files"
    fi

    if ! git -C "$ROOT" diff --cached --quiet; then
        git -C "$ROOT" commit -q -m "macOS Tahoe Liquid Glass for Ubuntu GNOME

Reproducible desktop transformation and automation framework.
Includes Liquid Glass materials, spring dock motion, measured palettes,
headless visual tests, backup/restore and portable release tooling.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
        ok "local commit created"
    else
        note "no local changes to commit"
    fi

    # 3) create the repository if needed
    local payload response http_code
    payload="$(jq -n --arg name "$repo" --arg desc "$description" \
        --argjson private "$private" \
        '{name:$name, private:$private, description:$desc,
          has_issues:true, has_wiki:false, has_projects:false}')"
    response="$(mktemp)"
    http_code="$(curl -sS -o "$response" -w '%{http_code}' \
        -X POST https://api.github.com/user/repos \
        -H "Authorization: Bearer ${token}" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        -d "$payload")"
    case "$http_code" in
        201) ok "repository created" ;;
        422)
            if github_api GET "/repos/${user}/${repo}" "" "$token" | jq -e '.full_name' >/dev/null; then
                note "repository already exists; updating it"
            else
                die "repository creation failed (422). Response: $(jq -r '.message // empty' "$response")"
            fi
            ;;
        401|403) die "GitHub authentication failed (HTTP ${http_code}); check the token scopes" ;;
        *) die "repository creation failed (HTTP ${http_code}): $(jq -r '.message // empty' "$response")" ;;
    esac
    local url
    url="$(jq -r '.html_url // empty' "$response")"
    [[ -n "$url" ]] || url="https://github.com/${user}/${repo}"
    rm -f "$response"

    # 4) remote without credentials in the URL
    if git -C "$ROOT" remote get-url origin >/dev/null 2>&1; then
        git -C "$ROOT" remote set-url origin "https://github.com/${user}/${repo}.git"
    else
        git -C "$ROOT" remote add origin "https://github.com/${user}/${repo}.git"
    fi

    # 5) push with an askpass helper; the token never enters git config/URL
    local askdir askpass
    askdir="$(mktemp -d)"
    askpass="$askdir/askpass.sh"
    cat >"$askpass" <<'ASKPASS'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' "x-access-token" ;;
  *) printf '%s\n' "${GITHUB_PUSH_TOKEN}" ;;
esac
ASKPASS
    chmod 700 "$askpass"
    if GIT_ASKPASS="$askpass" GITHUB_PUSH_TOKEN="$token" \
       GIT_TERMINAL_PROMPT=0 git -C "$ROOT" push -u origin main; then
        ok "pushed to ${url}"
    else
        rm -rf "$askdir"
        die "git push failed; the repository may be empty but was created at ${url}"
    fi
    rm -rf "$askdir"
    unset GITHUB_PUSH_TOKEN GH_TOKEN
    say ""
    say "${C_GREEN}${url}${C_RESET}"
}

# ── menu ──────────────────────────────────────────────────────────────────
show_menu() {
    cat <<EOF

${C_BOLD}macOS Tahoe Liquid Glass — manager${C_RESET}
${C_DIM}project: $ROOT${C_RESET}

  1) Status & verification          7) Capture screenshots (headless)
  2) Install                        8) Export portable release
  3) Dry run                        9) Restore original desktop
  4) Resume interrupted install    10) Uninstall
  5) Verify (with headless test)   11) Publish/update on GitHub
  6) Repair managed components     12) Logs & reports
                                   0) Exit
EOF
}

menu() {
    local choice
    while true; do
        show_menu
        read -r -p "Choose an option: " choice || exit 0
        case "$choice" in
            1) op_status ;;
            2) op_install ;;
            3) op_dryrun ;;
            4) op_resume ;;
            5) op_headless ;;
            6) op_repair ;;
            7) op_capture ;;
            8) op_export ;;
            9) op_restore ;;
            10) op_uninstall ;;
            11) op_publish ;;
            12) op_logs ;;
            0|q|Q) say "Bye."; exit 0 ;;
            *) warn "unknown option: $choice" ;;
        esac
        say ""
        read -r -p "Press Enter to return to the menu…" _ || true
    done
}

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next }
         NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

case "${1:-menu}" in
    menu) menu ;;
    status) op_status ;;
    install) shift; op_install "${1:-}" ;;
    dry-run|dryrun) shift; op_dryrun "${1:-}" ;;
    resume) op_resume ;;
    repair) op_repair ;;
    verify) op_verify ;;
    headless) op_headless ;;
    capture) op_capture ;;
    export) op_export ;;
    restore) shift; op_restore "${1:-}" ;;
    uninstall) op_uninstall ;;
    logs) op_logs ;;
    publish) op_publish ;;
    -h|--help|help) usage ;;
    *) usage; exit 2 ;;
esac
