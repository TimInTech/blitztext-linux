#!/usr/bin/env bash
# install.sh — Installationsskript für BlitztextLinux auf Ubuntu/Kubuntu
# Idempotent: kann mehrfach ausgeführt werden, ohne Schaden anzurichten.
set -euo pipefail

# ─── Farben & Hilfsfunktionen ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BOLD}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
err()     { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { err "$*"; exit 1; }
step()    { echo -e "\n${BOLD}▶ $*${RESET}"; }

# Protokolliert durchgeführte Aktionen für die abschließende Zusammenfassung
DONE_ITEMS=()
done_add() { DONE_ITEMS+=("$1"); }

resolve_hotkey_mode() {
    if [[ -n "${BLITZTEXT_NO_HOTKEY+x}" ]]; then
        case "${BLITZTEXT_NO_HOTKEY}" in
            0)
                HOTKEY_ENABLED=1
                ;;
            1)
                HOTKEY_ENABLED=0
                ;;
            *)
                die "BLITZTEXT_NO_HOTKEY muss 0 oder 1 sein (aktuell: ${BLITZTEXT_NO_HOTKEY})."
                ;;
        esac
        return
    fi

    if [[ ! -t 0 ]]; then
        HOTKEY_ENABLED=1
        return
    fi

    echo ""
    echo -e "${BOLD}Betriebsmodus wählen:${RESET}"
    echo "  1) Globale Hotkeys einrichten (empfohlen für volle Bedienung)"
    echo "  2) Nur Fenster/Tray nutzen (ohne input-Gruppe, ohne globale Hotkeys)"
    read -r -p "Auswahl [1/2, Standard: 1]: " hotkey_choice
    case "${hotkey_choice:-1}" in
        1)
            HOTKEY_ENABLED=1
            ;;
        2)
            HOTKEY_ENABLED=0
            ;;
        *)
            die "Ungültige Auswahl: ${hotkey_choice}"
            ;;
    esac
}

# apt-get mit Wartezeit auf den dpkg-Lock: Auf frisch installierten Ubuntu-
# Systemen blockiert unattended-upgrades den Lock oft minutenlang. Ohne
# Timeout brechen apt-Aufrufe sofort ab und reißen wegen `set -e` das
# gesamte Skript vor venv/torch-Installation ab.
APT_LOCK_TIMEOUT=300
apt_get() {
    sudo apt-get -o "DPkg::Lock::Timeout=${APT_LOCK_TIMEOUT}" "$@"
}

# ─── Pfade ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLITZTEXT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${BLITZTEXT_DIR}/.venv"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_SRC="${BLITZTEXT_DIR}/systemd/blitztext-linux.service"
SERVICE_DST="${SYSTEMD_USER_DIR}/blitztext-linux.service"

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

# ─── Voraussetzungen prüfen ───────────────────────────────────────────────────
step "Voraussetzungen prüfen"

# Nicht als root ausführen
if [[ "${EUID}" -eq 0 ]]; then
    die "Dieses Skript darf NICHT als root ausgeführt werden. Bitte als normaler Benutzer starten."
fi
ok "Läuft als Benutzer: $(whoami)"

# Ubuntu/Debian-basiertes System prüfen
if [[ ! -f /etc/os-release ]]; then
    die "/etc/os-release nicht gefunden — kein erkanntes Linux-System."
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *"ubuntu"* && "${ID_LIKE:-}" != *"debian"* && "${ID:-}" != "debian" && "${ID:-}" != "deepin" ]]; then
    die "Dieses Skript ist nur für Ubuntu/Debian-basierte Systeme gedacht (erkannt: ${ID:-unbekannt})."
fi
ok "Betriebssystem erkannt: ${PRETTY_NAME:-${ID}}"

# Python3 >= 3.10 prüfen
if ! command -v python3 &>/dev/null; then
    die "python3 nicht gefunden. Bitte 'sudo apt install python3' ausführen."
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "${PY_MAJOR}" -lt 3 || ( "${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -lt 10 ) ]]; then
    die "Python 3.10 oder neuer erforderlich (gefunden: ${PY_VERSION})."
fi
ok "Python-Version: ${PY_VERSION}"

HOTKEY_ENABLED=1
resolve_hotkey_mode
if [[ "${HOTKEY_ENABLED}" -eq 1 ]]; then
    ok "Betriebsmodus: Globale Hotkeys via evdev/input."
else
    ok "Betriebsmodus: Nur Fenster/Tray, ohne globale Hotkeys."
fi

# ─── apt-Pakete installieren ──────────────────────────────────────────────────
step "Systempakete prüfen und installieren"

APT_PACKAGES=(
    pulseaudio-utils
    wl-clipboard
    xclip
    ffmpeg
    python3-venv
    python3-evdev
    build-essential
    python3-dev
    socat
    pipx
)

MISSING_PKGS=()
for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "${pkg}" 2>/dev/null | grep -q "install ok installed"; then
        MISSING_PKGS+=("${pkg}")
    else
        ok "  ${pkg} bereits installiert"
    fi
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    info "Installiere fehlende Pakete: ${MISSING_PKGS[*]}"
    apt_get update -qq
    apt_get install -y "${MISSING_PKGS[@]}"
    done_add "Systempakete installiert: ${MISSING_PKGS[*]}"
    ok "Pakete installiert."
else
    ok "Alle Systempakete bereits vorhanden."
fi

if command -v ydotool &>/dev/null; then
    ok "  ydotool bereits im PATH gefunden: $(command -v ydotool)"
else
    info "ydotool nicht im PATH gefunden. Versuche Installation per apt ..."
    if apt_get install -y ydotool; then
        done_add "Systempaket installiert: ydotool"
        ok "ydotool installiert."
    else
        warn "ydotool konnte per apt nicht installiert werden. Bitte manuell installieren oder prüfen."
    fi
fi

# ─── Python venv einrichten ───────────────────────────────────────────────────
step "Virtuelles Python-Environment einrichten"

if [[ ! -d "${VENV_DIR}" ]]; then
    info "Erstelle .venv in ${VENV_DIR} ..."
    python3 -m venv "${VENV_DIR}"
    done_add ".venv erstellt unter ${VENV_DIR}"
    ok ".venv erstellt."
else
    ok ".venv bereits vorhanden: ${VENV_DIR}"
fi

PIP="${VENV_DIR}/bin/pip"

info "Aktualisiere pip ..."
"${PIP}" install --quiet --upgrade pip

# openai-whisper hängt von PyTorch ab. Der normale PyPI-Resolver zieht auf
# Linux oft CUDA-Wheels, die mehrere Gigabyte belegen und auf kleinen Ubuntu-/
# Kubuntu-Systemen schnell Quota-/Plattenplatzfehler auslösen. Blitztext nutzt
# standardmäßig CPU-Transkription, daher wird zuerst das CPU-only-Torch-Wheel
# installiert. Danach ist die torch-Abhängigkeit für openai-whisper bereits
# erfüllt und pip lädt keine CUDA-Pakete nach.
info "Installiere CPU-only PyTorch für Whisper ..."
"${PIP}" install --quiet --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

done_add "CPU-only PyTorch installiert"
ok "CPU-only PyTorch installiert."

PIP_PACKAGES=(PyQt6 evdev openai pytest openai-whisper faster-whisper)
info "Installiere pip-Pakete: ${PIP_PACKAGES[*]} ..."
"${PIP}" install --quiet --no-cache-dir "${PIP_PACKAGES[@]}"
done_add "pip-Pakete installiert: ${PIP_PACKAGES[*]}"
ok "pip-Pakete installiert."

# ─── Gruppe "input" ───────────────────────────────────────────────────────────
if [[ "${HOTKEY_ENABLED}" -eq 1 ]]; then
    step "Benutzergruppe 'input' prüfen"

    if groups "$(whoami)" | grep -qw "input"; then
        ok "Benutzer ist bereits Mitglied der Gruppe 'input'."
    else
        info "Füge $(whoami) zur Gruppe 'input' hinzu ..."
        sudo usermod -aG input "$(whoami)"
        done_add "Benutzer zur Gruppe 'input' hinzugefügt (Re-Login erforderlich!)"
        warn "WICHTIG: Sie müssen sich ab- und wieder anmelden (oder neu starten),"
        warn "         damit die Gruppenmitgliedschaft aktiv wird."
    fi
else
    step "Benutzergruppe 'input' überspringen"
    info "GUI/Tray-Modus gewählt: sudo usermod -aG input wird nicht ausgeführt."
    info "Blitztext startet nur mit Fenster/Tray-Bedienung; globale evdev-Hotkeys sind ohne input-Gruppe nicht aktiv."
fi

# ─── ydotool systemd-User-Service prüfen ─────────────────────────────────────
step "ydotool systemd-User-Service prüfen"

# BlitztextLinux verwendet ydotool nur, wenn auch ein ydotoold-Provider
# vorhanden ist. Ubuntu apt-ydotool 0.1.8 ist client-only; in diesem Fall bleibt
# Auto-Paste deaktiviert, Clipboard-Kopie funktioniert weiter.
if systemctl --user is-active --quiet ydotool.service 2>/dev/null; then
    ok "ydotool.service läuft bereits."
elif ydotoold_is_running; then
    ok "ydotoold läuft bereits mit Socket: $(ydotoold_socket_path)"
elif ydotool_user_service_exists; then
    if systemctl --user is-enabled --quiet ydotool.service 2>/dev/null; then
        ok "ydotool.service bereits aktiviert."
    else
        systemctl --user enable ydotool.service
        done_add "ydotool.service aktiviert"
        ok "ydotool.service aktiviert."
    fi

    systemctl --user start ydotool.service
    done_add "ydotool.service gestartet"
    ok "ydotool.service gestartet."
elif command -v ydotool &>/dev/null && ! ydotoold_provider_exists; then
    info "ydotool-Client gefunden, aber kein ydotoold-Provider."
    info "Ubuntu apt-ydotool 0.1.8 ist client-only; Auto-Paste bleibt dort nicht verfügbar."
    info "Blitztext kopiert Texte weiterhin ins Clipboard."
else
    warn "ydotoold wurde nicht gefunden oder läuft nicht."
    warn "Auto-Paste ist erst verfügbar, wenn ydotoold läuft oder ein ydotool.service existiert."
fi

# ─── blitztext-linux.service einrichten ───────────────────────────────────────
step "blitztext-linux systemd-User-Service einrichten"

if [[ ! -f "${SERVICE_SRC}" ]]; then
    die "Service-Datei nicht gefunden: ${SERVICE_SRC}"
fi

info "Kopiere Service-Datei und setze WorkingDirectory auf ${BLITZTEXT_DIR} ..."
mkdir -p "${SYSTEMD_USER_DIR}"
sed "s|%BLITZTEXT_DIR%|${BLITZTEXT_DIR}|g" "${SERVICE_SRC}" > "${SERVICE_DST}"
done_add "blitztext-linux.service installiert nach ${SERVICE_DST}"
ok "Service-Datei installiert."

systemctl --user daemon-reload

if systemctl --user is-enabled --quiet blitztext-linux 2>/dev/null; then
    ok "blitztext-linux.service bereits aktiviert (Autostart)."
else
    systemctl --user enable blitztext-linux
    done_add "blitztext-linux.service für Autostart aktiviert (nicht gestartet)"
    ok "blitztext-linux.service für Autostart aktiviert."
fi

# ─── Zusammenfassung ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Installation abgeschlossen${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}Durchgeführte Aktionen:${RESET}"
for item in "${DONE_ITEMS[@]}"; do
    echo -e "  ${GREEN}✔${RESET}  ${item}"
done

echo ""
echo -e "${BOLD}Betriebsmodus:${RESET}"
if [[ "${HOTKEY_ENABLED}" -eq 1 ]]; then
    echo -e "  ${GREEN}✔${RESET}  Globale Hotkeys via evdev/input sind vorgesehen."
else
    echo -e "  ${GREEN}✔${RESET}  GUI/Tray-Modus ohne globale Hotkeys ist vorgesehen."
    echo      "     Start/Stopp läuft über Fenster oder Tray; die input-Gruppe wurde nicht verändert."
fi

echo ""
echo -e "${BOLD}Nächste Schritte:${RESET}"
echo ""

if [[ "${HOTKEY_ENABLED}" -eq 0 ]]; then
    echo -e "  ${GREEN}✔${RESET}  Kein Re-Login für die input-Gruppe nötig."
else
    if id -Gn | grep -qw "input"; then
        echo -e "  ${GREEN}✔${RESET}  Gruppe 'input' ist in dieser Sitzung aktiv — kein Re-Login nötig."
    elif groups "$(whoami)" 2>/dev/null | grep -qw "input"; then
        echo -e "  ${YELLOW}1.${RESET}  ${BOLD}Re-Login durchführen${RESET} (oder System neu starten),"
        echo      "     damit die bereits eingetragene Gruppe 'input' in dieser Sitzung aktiv wird."
    else
        echo -e "  ${YELLOW}1.${RESET}  ${BOLD}Optional später Hotkeys aktivieren:${RESET}"
        echo      "     sudo usermod -aG input \$USER"
        echo      "     Danach ab- und wieder anmelden oder neu starten."
    fi
fi

echo ""
echo -e "  ${YELLOW}2.${RESET}  ${BOLD}Manuellen Test starten:${RESET}"
echo      "     cd ${BLITZTEXT_DIR}"
echo      "     ./run.sh"
echo ""
echo      "     (Falls Sie bereits im Projektverzeichnis sind, reicht: ./run.sh)"
echo ""
echo -e "  ${YELLOW}3.${RESET}  ${BOLD}Wenn alles funktioniert — Autostart aktivieren:${RESET}"
echo      "     systemctl --user start blitztext-linux"
echo ""
echo -e "  ${YELLOW}4.${RESET}  ${BOLD}Diagnose bei Problemen:${RESET}"
echo      "     bash scripts/verify.sh"
echo ""
