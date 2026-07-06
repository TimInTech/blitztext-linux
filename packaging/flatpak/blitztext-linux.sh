#!/bin/sh
# Flatpak-Launcher fuer BlitztextLinux (MVP-Spike).
#
# app/blitztext_linux.py fuegt sein Projektverzeichnis (der Elternordner von
# app/) beim Start selbst zu sys.path hinzu (siehe PROJECT_DIR-Logik am
# Dateianfang), daher genuegt ein direkter Aufruf ueber den vollen Pfad.
exec python3 /app/share/blitztext-linux/app/blitztext_linux.py "$@"
