"""PasteService for BlitztextLinux.

Kopiert/extrahiert aus whisper-dictation scripts/dictate_toggle.py v0.2.19.

Zwei Schritte:
  1. wl-copy/xclip  -- Text in Clipboard schreiben
  2. ydotool       -- Ctrl+V simulieren (nur wenn autopaste=True)

Fuer LLM-Workflows (text_improver, dampf_ablassen, emoji_text) wird
der rewritten Text eingefuegt, nicht das rohe Transkript.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger("blitztext.paste_service")

# Verzoegerung zwischen wl-copy und ydotool key (identisch zu whisper-dictation)
_PASTE_DELAY = 0.15
# ydotool key-delay in ms (identisch zu whisper-dictation)
_KEY_DELAY_MS = 80
# Strg+V als rohe Keycodes (`<keycode>:<pressed>`). ydotool >=1.0
# interpretiert KEINE Tastennamen mehr wie "ctrl+v" -- solche Werte werden
# stillschweigend als "nicht interpretierbar" behandelt und erzeugen nur einen
# Delay (rc=0, KEIN Fehler), sodass Auto-Paste unbemerkt ausbleibt.
# KEY_LEFTCTRL=29, KEY_V=47 (siehe /usr/include/linux/input-event-codes.h).
# Sequenz: Strg down, V down, V up, Strg up.
_CTRL_V_KEYCODES = ["29:1", "47:1", "47:0", "29:0"]
# Strg+Shift+V fuer Terminals (dort ist Strg+V meist "nichts tun" oder Copy).
# KEY_LEFTSHIFT=42 zusaetzlich zu KEY_LEFTCTRL=29, KEY_V=47.
_CTRL_SHIFT_V_KEYCODES = ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
# Bekannte Terminal-Emulator-Fensterklassen (lowercase-Vergleich). X11-only --
# unter Wayland gibt es ohne Compositor-spezifische Erweiterung keine
# generische "aktives Fenster"-Abfrage wie xdotool sie fuer X11 bietet.
_KNOWN_TERMINAL_WINDOW_CLASSES = frozenset(
    {
        "gnome-terminal-server",
        "xterm",
        "konsole",
        "kitty",
        "alacritty",
        "kgx",
        "tilix",
        "xfce4-terminal",
        "terminator",
        "mate-terminal",
        "org.wezfurlong.wezterm",
        "foot",
        "footclient",
        "lxterminal",
        "ghostty",
        "org.gnome.terminal",
        "com.github.alacritty.alacritty",
    }
)
# Subprocess-Timeouts: verhindern, dass ein haengendes wl-copy/ydotool den
# Transkriptions-Worker dauerhaft blockiert (sonst bleibt der App-State auf
# TRANSCRIBING/LLM_REWRITING haengen und kein neuer Hotkey-Toggle ist moeglich).
_WL_COPY_TIMEOUT = 5.0
_YDOTOOL_TIMEOUT = 5.0
_WL_PASTE_TIMEOUT = 5.0
_XCLIP_PASTE_TIMEOUT = 5.0
_XDOTOOL_TIMEOUT = 2.0
_COPYQ_TIMEOUT = 2.0
_YDOTOOL_MISSING_DAEMON_MARKERS = (
    "failed to connect",
    "no such file or directory",
    ".ydotool_socket",
    "connection refused",
)


def _detect_active_window_class() -> Optional[str]:
    # X11-only: xdotool benoetigt DISPLAY und kann unter Wayland ohne
    # Compositor-spezifische Erweiterungen das aktive Fenster nicht generisch abfragen.
    if not os.environ.get("DISPLAY"):
        return None
    if shutil.which("xdotool") is None:
        return None
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowclassname"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_XDOTOOL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        return None
    window_class = result.stdout.strip().lower()
    return window_class or None


def _is_terminal_active() -> bool:
    window_class = _detect_active_window_class()
    return bool(window_class and window_class in _KNOWN_TERMINAL_WINDOW_CLASSES)


class PasteServiceError(Exception):
    """Raised when clipboard write or key injection fails hard."""


class PasteService:
    """Schreibt Text ins Wayland-Clipboard und fuehrt optional Auto-Paste durch.

    Beispiel:
        svc = PasteService(autopaste=True)
        svc.paste("Hallo Welt")
    """

    def __init__(self, autopaste: bool = True, key_delay_ms: int = _KEY_DELAY_MS) -> None:
        """
        Args:
            autopaste: True = nach wl-copy automatisch Ctrl+V via ydotool senden.
            key_delay_ms: Verzögerung zwischen ydotool-Keyevents in Millisekunden.
        """
        self.autopaste = autopaste
        self.key_delay_ms = max(0, int(key_delay_ms))

    def paste(self, text: str, force_autopaste: Optional[bool] = None) -> None:
        """Text ins Clipboard schreiben und optional einfuegen.

        Args:
            text: Der einzufuegende Text.
            force_autopaste: Optionaler Override fuer den Auto-Paste-Schritt.

        Raises:
            PasteServiceError: Wenn wl-copy nicht gefunden oder hart fehlschlaegt.
        """
        if not text or not text.strip():
            logger.debug("paste() mit leerem Text aufgerufen, uebersprungen.")
            return

        do_autopaste = self.autopaste if force_autopaste is None else bool(force_autopaste)
        previous_clipboard = self._read_clipboard() if do_autopaste else None
        self._copy_to_clipboard(text)

        if do_autopaste and self._ydotool_paste():
            # Kurze Pause, damit die Ziel-App den eingefuegten Text uebernehmen kann
            time.sleep(_PASTE_DELAY)
            self._restore_clipboard(previous_clipboard)
            self._cleanup_copyq(text)

    def clipboard_only(self, text: str) -> None:
        """Nur Clipboard, kein ydotool -- fuer Faelle wo Auto-Paste unterwuenscht."""
        if not text or not text.strip():
            return
        self._copy_to_clipboard(text)

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _copy_to_clipboard(self, text: str) -> None:
        if _has_wayland_clipboard():
            self._wl_copy(text)
            return
        if _has_x11_clipboard():
            self._xclip_copy(text)
            return
        raise PasteServiceError(
            "Kein nutzbares Clipboard-Backend gefunden. Installieren: sudo apt install wl-clipboard xclip"
        )

    def _read_clipboard(self) -> Optional[str]:
        if _has_wayland_clipboard():
            command = ["wl-paste", "--no-newline"]
            timeout = _WL_PASTE_TIMEOUT
        elif _has_x11_clipboard():
            command = ["xclip", "-selection", "clipboard", "-o"]
            timeout = _XCLIP_PASTE_TIMEOUT
        else:
            return None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return None
        except (OSError, ValueError) as exc:
            logger.debug("Clipboard-Inhalt konnte nicht gelesen werden: %s", exc)
            return None
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return None
        if process.returncode != 0:
            return None
        if isinstance(stdout, bytes):
            try:
                return stdout.decode("utf-8")
            except UnicodeDecodeError as exc:
                logger.debug("Clipboard-Inhalt konnte nicht decodiert werden: %s", exc)
                return None
        return stdout

    def _restore_clipboard(self, previous: Optional[str]) -> None:
        if previous is None:
            return
        try:
            if _has_wayland_clipboard():
                self._wl_copy(previous)
                return
            if _has_x11_clipboard():
                self._xclip_copy(previous)
                return
            raise PasteServiceError("Kein Clipboard-Backend fuer Restore verfuegbar.")
        except PasteServiceError:
            logger.warning("Originalzwischenablage konnte nicht wiederhergestellt werden")

    def _cleanup_copyq(self, text: str) -> None:
        if shutil.which("copyq") is None:
            return
        try:
            result = subprocess.run(
                ["copyq", "read", "0"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=_COPYQ_TIMEOUT,
                text=True,
            )
            # "copyq read" haengt teils einen Zeilenumbruch an -- fuer den
            # Vergleich unerheblich, das eigentliche Entfernen bezieht sich
            # ohnehin auf den Index (Position 0), nicht auf den String.
            if result.stdout.rstrip("\n") != text:
                return
            subprocess.run(
                ["copyq", "remove", "0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_COPYQ_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            logger.debug("CopyQ-Cleanup uebersprungen: %s", exc)

    def _wl_copy(self, text: str) -> None:
        # WICHTIG: wl-copy forkt einen Hintergrund-Daemon, der die Auswahl
        # "besitzt". Dieser Kindprozess erbt offene Pipes -- mit stderr=PIPE
        # wartet subprocess.run() auf EOF und blockiert, bis der Clipboard-Daemon
        # stirbt (faelschlicherweise als Timeout sichtbar). Deshalb stderr nach
        # DEVNULL leiten, damit der Parent sofort zurueckkehrt.
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_WL_COPY_TIMEOUT,
            )
            logger.debug("wl-copy: %d Zeichen ins Clipboard geschrieben.", len(text))
        except subprocess.TimeoutExpired as exc:
            raise PasteServiceError(
                f"wl-copy reagierte nicht innerhalb von {_WL_COPY_TIMEOUT:.0f}s"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise PasteServiceError(f"wl-copy fehlgeschlagen (rc={exc.returncode})") from exc

    def _xclip_copy(self, text: str) -> None:
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_WL_COPY_TIMEOUT,
            )
            logger.debug("xclip: %d Zeichen ins Clipboard geschrieben.", len(text))
        except subprocess.TimeoutExpired as exc:
            raise PasteServiceError(
                f"xclip reagierte nicht innerhalb von {_WL_COPY_TIMEOUT:.0f}s"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise PasteServiceError(f"xclip fehlgeschlagen (rc={exc.returncode})") from exc

    def _ydotool_paste(self) -> bool:
        if shutil.which("ydotool") is None:
            logger.warning(
                "ydotool nicht gefunden -- Auto-Paste uebersprungen. "
                "Installieren: sudo apt install ydotool"
            )
            return False
        # Kurze Pause, damit der neue Clipboard-Inhalt vor Ctrl+V sicher anliegt
        time.sleep(_PASTE_DELAY)
        keycodes = _CTRL_SHIFT_V_KEYCODES if _is_terminal_active() else _CTRL_V_KEYCODES
        if keycodes is _CTRL_SHIFT_V_KEYCODES:
            logger.debug("Aktives Fenster ist ein Terminal -- sende Ctrl+Shift+V via ydotool.")
        else:
            logger.debug("Aktives Fenster ist kein Terminal -- sende Ctrl+V via ydotool.")
        try:
            result = subprocess.run(
                ["ydotool", "key", "--key-delay", str(self.key_delay_ms), *keycodes],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=_YDOTOOL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # Nicht fatal -- Clipboard-Inhalt ist bereits gesetzt. Wichtig: nicht
            # blockieren, damit der Worker zurueckkehrt und der State auf IDLE faellt.
            logger.warning(
                "ydotool Ctrl+V Timeout nach %.0fs -- Auto-Paste uebersprungen "
                "(Text liegt bereits im Clipboard).",
                _YDOTOOL_TIMEOUT,
            )
            return False
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip() if result.stderr else ""
            # Nicht fatal -- Clipboard-Inhalt ist bereits gesetzt
            if _looks_like_missing_ydotoold(stderr):
                logger.warning(
                    "ydotoold nicht verfügbar -- Auto-Paste uebersprungen "
                    "(Text liegt bereits im Clipboard)."
                )
                return False
            logger.warning("ydotool Ctrl+V fehlgeschlagen (rc=%d): %s", result.returncode, stderr)
            return False
        return True


def check_dependencies() -> list[str]:
    """Gibt eine Liste fehlender System-Abhaengigkeiten zurueck.

    Verwendet von install.sh-Verifikation und Einstellungs-Dialog.
    """
    missing = []
    if shutil.which("wl-copy") is None and shutil.which("xclip") is None:
        missing.append("wl-clipboard oder xclip")
    if shutil.which("ydotool") is None:
        missing.append("ydotool")
    return missing


def _has_wayland_clipboard() -> bool:
    if shutil.which("wl-copy") is None:
        return False
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    if wayland_display:
        return bool(runtime_dir and os.path.exists(os.path.join(runtime_dir, wayland_display)))
    return not os.environ.get("DISPLAY")


def _has_x11_clipboard() -> bool:
    return bool(os.environ.get("DISPLAY") and shutil.which("xclip") is not None)


def _looks_like_missing_ydotoold(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _YDOTOOL_MISSING_DAEMON_MARKERS)
