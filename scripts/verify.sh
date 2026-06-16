#!/usr/bin/env bash
# verify.sh — Schnell-Check aller BlitztextLinux-Abhängigkeiten
# Läuft ohne root und ohne Schreibzugriff.
# Format: PASS / FAIL / WARN / INFO pro Prüfung.
set -uo pipefail

# ─── Farben ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Zähler ───────────────────────────────────────────────────────────────────
COUNT_PASS=0
COUNT_FAIL=0
COUNT_WARN=0

pass() { echo -e "${GREEN}[PASS]${RESET}  $*"; (( COUNT_PASS++ )) || true; }
fail() { echo -e "${RED}[FAIL]${RESET}  $*"; (( COUNT_FAIL++ )) || true; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; (( COUNT_WARN++ )) || true; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }

# ─── Hilfsfunktion: Versionsnummer vergleichen ────────────────────────────────
# version_ge <ist> <min>  — gibt 0 zurück wenn ist >= min
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# ─── Pfade ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLITZTEXT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${BLITZTEXT_DIR}/.venv/bin/python"

ydotoold_socket_path() {
    echo "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket"
}

ydotoold_is_running() {
    local socket_path
    socket_path="$(ydotoold_socket_path)"
    pgrep -x ydotoold >/dev/null 2>&1 && [[ -S "${socket_path}" ]]
}

ydotool_user_service_exists() {
    systemctl --user cat ydotool.service >/dev/null 2>&1
}

ydotoold_provider_exists() {
    command -v ydotoold >/dev/null 2>&1 || ydotool_user_service_exists
}

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  BlitztextLinux — Abhängigkeits-Check${RESET}"
echo -e "${BOLD}  Verzeichnis: ${BLITZTEXT_DIR}${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}── Systembinaries ───────────────────────────────────${RESET}"

# parec (pulseaudio-utils)
if command -v parec &>/dev/null; then
    pass "parec gefunden: $(command -v parec)"
else
    fail "parec nicht gefunden — 'sudo apt install pulseaudio-utils'"
fi

# wl-copy (wl-clipboard)
if command -v wl-copy &>/dev/null; then
    pass "wl-copy gefunden: $(command -v wl-copy)"
else
    fail "wl-copy nicht gefunden — 'sudo apt install wl-clipboard'"
fi

# xclip (X11 clipboard fallback)
if command -v xclip &>/dev/null; then
    pass "xclip gefunden: $(command -v xclip)"
else
    warn "xclip nicht gefunden — X11-Clipboard-Fallback fehlt ('sudo apt install xclip')"
fi

# ydotool
if command -v ydotool &>/dev/null; then
    pass "ydotool gefunden: $(command -v ydotool)"
else
    fail "ydotool nicht gefunden — 'sudo apt install ydotool'"
fi

# ffmpeg
if command -v ffmpeg &>/dev/null; then
    pass "ffmpeg gefunden: $(command -v ffmpeg)"
else
    fail "ffmpeg nicht gefunden — 'sudo apt install ffmpeg'"
fi

# socat
if command -v socat &>/dev/null; then
    pass "socat gefunden: $(command -v socat)"
else
    fail "socat nicht gefunden — 'sudo apt install socat'"
fi

echo ""
echo -e "${BOLD}── Python ────────────────────────────────────────────${RESET}"

# python3 >= 3.10
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    PY_SHORT=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if version_ge "${PY_SHORT}" "3.10"; then
        pass "python3 >= 3.10: ${PY_VER}"
    else
        fail "python3 zu alt (${PY_VER}) — mindestens 3.10 erforderlich"
    fi
else
    fail "python3 nicht gefunden"
fi

# .venv vorhanden
if [[ -x "${VENV_PYTHON}" ]]; then
    VENV_VER=$("${VENV_PYTHON}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    pass ".venv/bin/python vorhanden (${VENV_VER})"
else
    fail ".venv/bin/python nicht gefunden — 'bash scripts/install.sh' ausführen"
fi

echo ""
echo -e "${BOLD}── Python-Pakete im .venv ───────────────────────────${RESET}"

# PyQt6
if [[ -x "${VENV_PYTHON}" ]]; then
    if "${VENV_PYTHON}" -c "import PyQt6" 2>/dev/null; then
        PYQT_VER=$("${VENV_PYTHON}" -c "from PyQt6.QtCore import PYQT_VERSION_STR; print(PYQT_VERSION_STR)" 2>/dev/null || echo "?")
        pass "PyQt6 importierbar (${PYQT_VER})"
    else
        fail "PyQt6 nicht importierbar — '.venv/bin/pip install PyQt6'"
    fi

    # evdev
    if "${VENV_PYTHON}" -c "import evdev" 2>/dev/null; then
        pass "evdev importierbar"
    else
        fail "evdev nicht importierbar — '.venv/bin/pip install evdev'"
    fi

    # openai
    if "${VENV_PYTHON}" -c "import openai" 2>/dev/null; then
        OPENAI_VER=$("${VENV_PYTHON}" -c "import openai; print(openai.__version__)" 2>/dev/null || echo "?")
        pass "openai importierbar (${OPENAI_VER})"
    else
        fail "openai nicht importierbar — '.venv/bin/pip install openai'"
    fi
else
    warn "Überspringe Paket-Checks (kein .venv gefunden)"
fi

echo ""
echo -e "${BOLD}── Whisper-Backends im .venv ────────────────────────${RESET}"

if [[ -x "${VENV_PYTHON}" ]]; then
    if "${VENV_PYTHON}" -c "import whisper" 2>/dev/null; then
        pass "openai-whisper im .venv importierbar"
    else
        fail "openai-whisper nicht im .venv importierbar — 'bash scripts/install.sh'"
    fi

    if "${VENV_PYTHON}" -c "import faster_whisper" 2>/dev/null; then
        pass "faster-whisper im .venv importierbar"
    else
        warn "faster-whisper nicht im .venv importierbar — 'bash scripts/install.sh'"
    fi
else
    warn "Überspringe Whisper-Backend-Checks (kein .venv gefunden)"
fi

echo ""
echo -e "${BOLD}── Benutzer & Gruppen ───────────────────────────────${RESET}"

# Gruppe "input"
if id -Gn | grep -qw "input"; then
    pass "Gruppe 'input' ist in dieser Sitzung aktiv"
elif groups "$(whoami)" 2>/dev/null | grep -qw "input"; then
    warn "Benutzer ist in /etc/group für 'input' eingetragen, aber die aktuelle Sitzung nutzt die Gruppe noch nicht"
    warn "  Behebung: Re-Login durchführen oder System neu starten"
else
    warn "Benutzer NICHT in Gruppe 'input' — evdev-Hotkeys funktionieren nicht"
    warn "  Behebung: sudo usermod -aG input \$USER  (dann Re-Login)"
fi

echo ""
echo -e "${BOLD}── Systemd-User-Services ────────────────────────────${RESET}"

# ydotool
if systemctl --user is-active --quiet ydotool.service 2>/dev/null; then
    pass "ydotool.service läuft als User-Service"
elif ydotoold_is_running; then
    pass "ydotoold läuft bereits mit Socket: $(ydotoold_socket_path)"
elif ydotool_user_service_exists; then
    warn "ydotool.service ist vorhanden, läuft aber NICHT — Auto-Paste funktioniert möglicherweise nicht"
    warn "  Behebung: systemctl --user start ydotool.service"
elif command -v ydotool &>/dev/null && ! ydotoold_provider_exists; then
    info "ydotool-Client vorhanden, aber kein ydotoold-Provider erkannt"
    info "  Erwartet bei Ubuntu apt-ydotool 0.1.8-3build1; Auto-Paste ist dort nicht verfügbar"
    info "  Clipboard-Kopie bleibt verfügbar; für Auto-Paste ydotoold aus Source oder per User-Service bereitstellen"
else
    warn "ydotoold wurde nicht gefunden oder läuft nicht mit Socket"
    warn "  Auto-Paste benötigt ydotoold oder einen passenden systemd-User-Service"
fi

echo ""
echo -e "${BOLD}── Wayland / Laufzeitumgebung ───────────────────────${RESET}"

# Desktop display
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    pass "WAYLAND_DISPLAY gesetzt: ${WAYLAND_DISPLAY}"
elif [[ -n "${DISPLAY:-}" ]]; then
    pass "DISPLAY gesetzt: ${DISPLAY} (X11-Session)"
else
    warn "Weder WAYLAND_DISPLAY noch DISPLAY gesetzt — Clipboard/GUI funktionieren möglicherweise nicht"
fi

# XDG_RUNTIME_DIR
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    if [[ -d "${XDG_RUNTIME_DIR}" ]]; then
        pass "XDG_RUNTIME_DIR gesetzt und existiert: ${XDG_RUNTIME_DIR}"
    else
        fail "XDG_RUNTIME_DIR gesetzt, Verzeichnis existiert aber NICHT: ${XDG_RUNTIME_DIR}"
    fi
else
    fail "XDG_RUNTIME_DIR nicht gesetzt — systemd-User-Services und Sockets werden nicht funktionieren"
fi

echo ""
echo -e "${BOLD}── Konfiguration ────────────────────────────────────${RESET}"

CONFIG_FILE="${HOME}/.config/blitztext-linux/config.json"
if [[ -f "${CONFIG_FILE}" ]]; then
    # Berechtigungen prüfen
    PERMS=$(stat -c "%a" "${CONFIG_FILE}" 2>/dev/null || echo "???")
    if [[ "${PERMS}" == "600" ]]; then
        pass "config.json vorhanden und korrekt geschützt (0600)"
    else
        warn "config.json vorhanden, aber Berechtigungen sind ${PERMS} (erwartet: 600)"
        warn "  Behebung: chmod 600 ${CONFIG_FILE}"
    fi
else
    info "config.json nicht gefunden — wird beim ersten Start automatisch erstellt"
    info "  Pfad: ${CONFIG_FILE}"
fi

# ─── Zusammenfassung ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Ergebnis: ${GREEN}${COUNT_PASS} PASS${RESET}${BOLD} / ${RED}${COUNT_FAIL} FAIL${RESET}${BOLD} / ${YELLOW}${COUNT_WARN} WARN${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo ""

if [[ "${COUNT_FAIL}" -gt 0 ]]; then
    echo -e "${RED}Es gibt ${COUNT_FAIL} fehlgeschlagene Prüfung(en).${RESET}"
    echo    "Führen Sie 'bash scripts/install.sh' aus, um fehlende Abhängigkeiten zu installieren."
    echo ""
    exit 1
elif [[ "${COUNT_WARN}" -gt 0 ]]; then
    echo -e "${YELLOW}Alle Pflicht-Abhängigkeiten vorhanden, aber ${COUNT_WARN} Warnung(en) beachten.${RESET}"
    echo ""
    exit 0
else
    echo -e "${GREEN}Alle Prüfungen bestanden — BlitztextLinux ist bereit.${RESET}"
    echo ""
    exit 0
fi
