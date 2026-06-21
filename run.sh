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
    if [[ ! -O "${SECRETS_FILE}" ]]; then
        echo "WARNUNG: ${SECRETS_FILE} gehört nicht dem aktuellen Nutzer und wird nicht geladen." >&2
    else
        SECRETS_PERMS=$(stat -c '%a' "${SECRETS_FILE}" 2>/dev/null || true)
        if [[ -n "${SECRETS_PERMS}" ]] && (( 10#${SECRETS_PERMS} > 600 )); then
            echo "WARNUNG: ${SECRETS_FILE} hat zu offene Rechte (${SECRETS_PERMS}); erwartet 600 oder restriktiver." >&2
        fi
        set -a
        # shellcheck disable=SC1090
        source "${SECRETS_FILE}"
        set +a
    fi
fi

# --- venv-Prüfung ---
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "FEHLER: .venv nicht gefunden. Bitte zuerst 'bash scripts/install.sh' ausführen." >&2
    exit 1
fi

exec "${VENV_PYTHON}" "${SCRIPT_DIR}/app/blitztext_linux.py" "$@"
