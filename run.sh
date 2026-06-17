#!/usr/bin/env bash
# BlitztextLinux starten — immer mit der .venv (nicht mit dem System-python3)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
LOCKFILE="${XDG_RUNTIME_DIR:-/tmp}/blitztext_linux.pid"
SECRETS_FILE="${HOME}/.config/blitztext-linux/secrets.env"

# --- Single-Instance-Guard ---
if [[ -f "${LOCKFILE}" ]]; then
    OLD_PID="$(cat "${LOCKFILE}")"
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "BlitztextLinux läuft bereits (PID ${OLD_PID}). Abbruch." >&2
        exit 1
    else
        echo "Stale PID ${OLD_PID} gefunden – wird bereinigt." >&2
        rm -f "${LOCKFILE}"
    fi
fi
echo $$ > "${LOCKFILE}"
trap 'rm -f "${LOCKFILE}"' EXIT INT TERM

# --- secrets.env (optional) ---
if [[ -f "${SECRETS_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${SECRETS_FILE}"
    set +a
fi

# --- venv-Prüfung ---
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "FEHLER: .venv nicht gefunden. Bitte zuerst 'bash scripts/install.sh' ausführen." >&2
    exit 1
fi

exec "${VENV_PYTHON}" "${SCRIPT_DIR}/app/blitztext_linux.py" "$@"
