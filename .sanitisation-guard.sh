#!/usr/bin/env bash
# .sanitisation-guard.sh
#
# A pre-push gate. Fails if anything in the tracked tree looks like a secret, a personal
# path, a real email address, a private system identifier, or a confidentiality marker.
#
# Two layers:
#   1. Generic checks (this file, committed): API-key shapes, private-key headers, home
#      directories, email addresses that are not obvious placeholders, 15+ digit IDs
#      (the shape of Smartsheet / Telegram / Notion identifiers), confidentiality markers.
#   2. Local banlist (.guard-banlist.local, gitignored, optional): one case-insensitive
#      extended regex per line for terms specific to you or your organisation. Keep it out
#      of git; the whole point is that the public repo never names them.
#
# Style check (warning only): em dashes. House style uses a colon, a comma, or a rewrite.
#
# Usage:  bash .sanitisation-guard.sh          exit 0 = clean, exit 1 = findings
# CI:     .github/workflows/guard.yml runs this on every push and pull request.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SELF=".sanitisation-guard.sh"
LOCAL_BANLIST=".guard-banlist.local"
EXCLUDES=(--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__
          --exclude-dir=state --exclude-dir=.cache --exclude-dir=raw
          --exclude="$SELF" --exclude="$LOCAL_BANLIST" --exclude="*.log" --exclude="*.png" --exclude="*.jpg" --exclude="*.gif"
          --exclude="*.lock" --exclude="package-lock.json" --exclude="*.min.js")

status=0
report() { printf '\n[%s] %s\n' "$1" "$2"; }

# 1a. Secrets and key shapes ---------------------------------------------------------------
KEYS='sk-ant-[A-Za-z0-9_-]{12,}|sk-or-v1-[A-Za-z0-9]{12,}|sk-proj-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY'
if hits=$(grep -rnEI "${EXCLUDES[@]}" "$KEYS" . 2>/dev/null) && [ -n "$hits" ]; then
  report FAIL "credential-shaped strings"; echo "$hits"; status=1
fi

# 1b. Home directories and machine-specific paths -----------------------------------------
PATHS='/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|C:\\\\Users\\\\'
if hits=$(grep -rnEI "${EXCLUDES[@]}" "$PATHS" . 2>/dev/null) && [ -n "$hits" ]; then
  report FAIL "machine-specific paths (use ~ or a variable)"; echo "$hits"; status=1
fi

# 1c. Email addresses that are not obvious placeholders -----------------------------------
EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
ALLOWED='@example\.(com|org|net)|@your-?(org|company|domain)|users\.noreply\.github\.com|@localhost'
if hits=$(grep -rnEI "${EXCLUDES[@]}" "$EMAIL" . 2>/dev/null | grep -vE "$ALLOWED") && [ -n "$hits" ]; then
  report FAIL "email addresses (use name@example.com)"; echo "$hits"; status=1
fi

# 1d. Long numeric identifiers (the 16-digit shape of sheet / workspace IDs). Millisecond
#     timestamps are 13 digits and pass; anything 15+ digits is almost always an identifier.
if hits=$(grep -rnEI "${EXCLUDES[@]}" '(^|[^0-9.])[0-9]{15,20}([^0-9.]|$)' . 2>/dev/null | grep -vE '(^|[^0-9])(0{15,20}|1{15,20}|9{15,20})([^0-9]|$)'); [ -n "$hits" ]; then
  report FAIL "15+ digit identifiers (replace with a placeholder like 0000000000000000)"; echo "$hits"; status=1
fi

# 1e. Confidentiality markers -------------------------------------------------------------
if hits=$(grep -rnEI "${EXCLUDES[@]}" 'CONFIDENTIAL|INTERNAL ONLY|DO NOT DISTRIBUTE|COMMERCIAL[- ]IN[- ]CONFIDENCE' . 2>/dev/null) && [ -n "$hits" ]; then
  report FAIL "confidentiality markers"; echo "$hits"; status=1
fi

# 2. Local banlist (optional) --------------------------------------------------------------
if [ -f "$LOCAL_BANLIST" ]; then
  # strip comments and blank lines, join into one alternation
  pattern=$(grep -vE '^\s*(#|$)' "$LOCAL_BANLIST" | paste -sd '|' -)
  if [ -n "$pattern" ]; then
    if hits=$(grep -rnEiI "${EXCLUDES[@]}" "$pattern" . 2>/dev/null) && [ -n "$hits" ]; then
      report FAIL "local banlist terms"; echo "$hits"; status=1
    fi
  fi
fi

# 3. Style: em dashes (warning only) --------------------------------------------------------
if hits=$(grep -rnI "${EXCLUDES[@]}" -F -- "$(printf '\xe2\x80\x94')" . 2>/dev/null) && [ -n "$hits" ]; then
  report WARN "em dashes (house style: colon, comma, or rewrite)"; echo "$hits"
fi

if [ "$status" -eq 0 ]; then
  echo "PASS: sanitisation guard found nothing to block"
else
  echo
  echo "FAIL: fix the findings above before pushing"
fi
exit "$status"
