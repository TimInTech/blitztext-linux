# Flatpak-MVP-Spike (packaging/flatpak/)

Minimaler, lokal getesteter Ansatz, um BlitztextLinux als GUI-App in einer
Flatpak-Sandbox zu starten. Kein Release-, Flathub- oder Signing-Setup.

## Umfang (MVP)

Absichtlich enthalten:
- Qt6-GUI (`org.kde.Platform`/`org.kde.Sdk` 6.8)
- Zwischenablage ueber den bestehenden Qt-Clipboard-Fallback
  (`app/paste_service.py`, bereits in PR #47 gehaertet)
- Audioaufnahme ueber PulseAudio-Socket
- Cloud-Aufrufe (OpenAI: LLM-Workflows, ggf. Transkription/TTS) ueber
  `--share=network`
- D-Bus-Zugriff auf `org.kde.StatusNotifierWatcher`
  (`--talk-name=org.kde.StatusNotifierWatcher`) fuer das Tray-Icon --
  siehe "Tray-Icon erfordert D-Bus-Talk-Name" unten, App startet
  ausschliesslich als Tray-Icon (`app/blitztext_linux.py::setup_tray`),
  ohne diese Berechtigung ist die GUI im Sandbox unerreichbar.

Absichtlich **nicht** enthalten / sichtbar deaktiviert:
- Globale Hotkeys (evdev) -- `app/hotkey_service.py` importiert `evdev` lazy
  und liefert im Flatpak bereits den Hinweis
  "Globale Hotkeys sind im Flatpak nicht verfügbar"
  (siehe `tests/test_flatpak_fallback.py::test_hotkey_service_flatpak_hint`).
  Der Sandbox fehlt bewusst jeder Input-Device-Zugriff
  (kein `--device=all`, kein `input`-Gruppen-Aequivalent).
- Auto-Paste via `ydotool` (kein Provider im Sandbox vorgesehen; Clipboard-
  Kopie funktioniert weiter, siehe bestehender Fallback-Test
  `test_paste_service_autopaste_without_ydotool`).
- Lokale Whisper-Transkription (`openai-whisper`/`faster-whisper`/`torch`):
  bewusst aus `requirements-flatpak.txt` ausgeklammert, da der Download
  mehrere GB umfasst. `app/transcribe.py` importiert `whisper` ebenfalls
  lazy, das Modul ist fuer eine spaetere Erweiterung vorbereitet.
- Desktop-Notifications (`notify-send` ist im Sandbox nicht gebuendelt;
  `app/notify.py` degradiert bereits stillschweigend, wenn das Binary fehlt).

## Dateien

- `io.github.TimInTech.BlitztextLinux.yaml` -- Flatpak-Manifest.
  `io.github.TimInTech.*` ist ein Platzhalter-App-ID-Namespace (an das
  GitHub-Repo `TimInTech/blitztext-linux` angelehnt), nicht auf Flathub
  registriert.
- `blitztext-linux.sh` -- Launcher, ruft `app/blitztext_linux.py` direkt auf.
- `requirements-flatpak.txt` -- reduzierte pip-Abhaengigkeiten fuer den
  Sandbox-Build (nur `PyQt6` + `openai`).

## Bekannte Abweichungen von Flathub-Konventionen

- Das `blitztext-linux-deps`-Modul installiert pip-Pakete direkt aus PyPI
  waehrend des Builds (`--share=network` nur fuer dieses Modul). Flathub
  verlangt gepinnte/vendored Quellen (z. B. via `flatpak-pip-generator`).
  Fuer diesen lokalen MVP-Spike bewusst nicht umgesetzt.
- Kein AppStream-Metadata-File, kein `.desktop`-File, kein Icon --
  ausserhalb dieses Ordners wurden bewusst keine Dateien angelegt.
- `notes_folder`-Export (`~/Blitztext-Notizen`, siehe `app/config.py`)
  liegt ausserhalb des sandboxed `$HOME`; ohne zusaetzliches
  `--filesystem=home` bleibt dieser Pfad im Flatpak unerreichbar. Nicht
  Teil des MVP-Scopes, hier nur dokumentiert.

## Verifikation (in diesem Spike durchgefuehrt)

`flatpak-builder` 1.4.8 ist auf diesem Host vorhanden. Zunaechst wurde nur
strukturell validiert, ohne Runtime-Install:

```bash
flatpak-builder --show-manifest packaging/flatpak/io.github.TimInTech.BlitztextLinux.yaml
flatpak-builder --show-deps packaging/flatpak/io.github.TimInTech.BlitztextLinux.yaml
```

Nach PR #48 wurde zusaetzlich ein echter Build (inkl. Download von
`org.kde.Platform`/`org.kde.Sdk` 6.8, ca. 1,5 GB) erfolgreich getestet.

### Hinweis: Build-State-Dir unter `/tmp`

Wenn das Build-Verzeichnis unter `/tmp` liegt, kann `flatpak-builder`
je nach Setup versuchen, seinen State-Ordner (`.flatpak-builder/`) relativ
zum Home-Filesystem anzulegen. Da `/tmp` haeufig ein separates `tmpfs` ist,
schlagen manche Operationen (z. B. `rofiles-fuse`/Hardlinks) ueber die
Filesystem-Grenze fehl. Abhilfe: State-Dir explizit auf denselben
Filesystem-Mountpoint wie das Build-Ziel legen, z. B.:

```bash
--state-dir=/tmp/blitztext-flatpak-builder-state
```

### Beispiel-Build-Befehl (ohne `--install`)

```bash
flatpak install --user -y flathub org.kde.Platform//6.8 org.kde.Sdk//6.8
flatpak-builder --force-clean \
  --state-dir=/tmp/blitztext-flatpak-builder-state \
  /tmp/blitztext-flatpak-build \
  packaging/flatpak/io.github.TimInTech.BlitztextLinux.yaml
```

Bewusst ohne `--install` -- der Build wird nur erzeugt, nicht in die lokale
Flatpak-Umgebung installiert. Fuer einen manuellen Testlauf danach:

```bash
flatpak-builder --run /tmp/blitztext-flatpak-build \
  packaging/flatpak/io.github.TimInTech.BlitztextLinux.yaml \
  blitztext-linux.sh
```

### Tray-Icon erfordert D-Bus-Talk-Name

Beim ersten echten `flatpak run`-Testlauf (nach PR #48) blieb die App
unerreichbar: kein Absturz, Prozess lief stabil (`flatpak ps` zeigte ihn),
aber es erschien weder Tray-Icon noch Fenster. Ursache: Blitztext startet
ausschliesslich als Tray-Icon (`app/blitztext_linux.py::setup_tray`, Zeile
~645/673-781), das Hauptfenster oeffnet sich erst per Klick darauf. Ohne
`--talk-name=org.kde.StatusNotifierWatcher` im Manifest kann Qt
(`QDBusTrayIcon`, KDE-Style) das StatusNotifierItem nicht beim Watcher
registrieren (`QDBusError("org.freedesktop.DBus.Error.ServiceUnknown")`
im Log) -- damit gab es keinen Weg, die GUI ueberhaupt zu oeffnen.

Fix: `--talk-name=org.kde.StatusNotifierWatcher` zu `finish-args`
hinzugefuegt (kein breiterer `--socket=session-bus`, um beim
Minimal-Rechte-Ansatz des MVP zu bleiben). Nach Rebuild + Neuinstallation
registrierte sich das Tray-Item nachweisbar per D-Bus
(`busctl --user call ... org.kde.StatusNotifierItem Title` lieferte
`"Blitztext"`), kein `ServiceUnknown`-Fehler mehr im Log.

### KDE Platform/Sdk 6.8 -- EOL-Hinweis

Laut Flathub ist `org.kde.Platform`/`org.kde.Sdk` 6.8 als EOL markiert.
Fuer diesen MVP ist die Runtime weiterhin funktionsfaehig und wurde
erfolgreich gebaut. Naechster Upgrade-Kandidat: **6.10**. Ein Runtime-Bump
ist nicht Teil dieses Spikes.

## Naechster Schritt (nicht Teil dieses Spikes)

Falls ein vollstaendig installierter Testlauf gewuenscht ist:

```bash
flatpak-builder --user --install --force-clean build-dir \
  packaging/flatpak/io.github.TimInTech.BlitztextLinux.yaml
flatpak run io.github.TimInTech.BlitztextLinux
```

Rollback: `packaging/flatpak/` einfach loeschen bzw. den Branch
`spike/flatpak-manifest-mvp` verwerfen -- keine Aenderungen ausserhalb
dieses Ordners.
