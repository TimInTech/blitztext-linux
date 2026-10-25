#!/usr/bin/env bash
# BlitztextLinux starten — immer mit der .venv (nicht mit dem System-python3)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolve the pointer once, then invoke Python directly: no launcher recursion.
# Incomplete or broken current installations fall back to the retained release.
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
if [[ "${DATA_HOME}" != /* ]]; then DATA_HOME="${HOME}/.local/share"; fi
RELEASES_DIR="${DATA_HOME}/blitztext-linux/releases"
APP_DIR="${SCRIPT_DIR}"
if [[ -z "${FLATPAK_ID:-}" && ! -f /.flatpak-info ]]; then
    RELEASES_REAL="$(readlink -f -- "${RELEASES_DIR}" 2>/dev/null || true)"
    for POINTER in current previous; do
        [[ -L "${RELEASES_DIR}/${POINTER}" ]] || continue
        TARGET="$(readlink -f -- "${RELEASES_DIR}/${POINTER}" 2>/dev/null || true)"
        [[ -n "${TARGET}" && "$(dirname "${TARGET}")" == "${RELEASES_REAL}" ]] || continue
        [[ "$(basename "${TARGET}")" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[a-f0-9]+$ ]] || continue
        if [[ -f "${TARGET}/.ready" && -f "${TARGET}/app/blitztext_linux.py" && -x "${TARGET}/.venv/bin/python" ]]; then
            APP_DIR="${TARGET}"
            break
        fi
    done
fi
VENV_PYTHON="${APP_DIR}/.venv/bin/python"
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
        if [[ -n "${SECRETS_PERMS}" ]] && (( (8#${SECRETS_PERMS} & 8#077) != 0 )); then
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

exec "${VENV_PYTHON}" "${APP_DIR}/app/blitztext_linux.py" "$@"
