"""Desktop-Benachrichtigungen via notify-send.

Portiert aus whisper-dictation app/gui/notify.py. Schlaegt nie hart fehl --
fehlt notify-send, wird die Meldung still uebersprungen.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger("blitztext.notify")

_NOTIFY_TIMEOUT = 5.0


def notify(
    title: str,
    body: str,
    urgency: str = "normal",
    icon: str = "audio-input-microphone",
) -> None:
    """Sendet eine Desktop-Benachrichtigung ohne bei OS-Problemen zu werfen."""
    if shutil.which("notify-send") is None:
        logger.debug("notify-send nicht gefunden -- Benachrichtigung uebersprungen.")
        return
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-i", icon, title, body],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_NOTIFY_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass


def is_available() -> bool:
    return shutil.which("notify-send") is not None
