# Repository-Bereinigung und Review-Abschluss

Datum: 2026-09-02
Repository: `TimInTech/blitztext-linux`

## Ziel

Das Repository endet in einem nachweislich funktionsfähigen und vollständig
aufgeräumten Zustand:

- lokal und auf GitHub existiert nur der Branch `main`;
- der lokale Arbeitsbaum ist sauber;
- es gibt keine offenen Pull Requests oder Issues;
- sämtliche historischen Review-Threads sind fachlich geprüft und aufgelöst;
- der aktuelle `main`-Commit besteht die vollständige lokale Testsuite und die
  GitHub-Actions-Matrix für Python 3.11, 3.12 und 3.14;
- bekannte reale Review-Befunde bleiben nicht lediglich als aufgelöste
  Metadaten zurück, sondern werden testgetrieben behoben.

## Ausgangslage

- Lokal liegt `main` mit dem CI-Testcommit `8f4468d` einen Commit vor
  `origin/main` (`c312a51`).
- Der aktuelle reguläre GitHub-CI-Lauf `33449604331` ist wegen zweier
  veralteter ydotool-Testannahmen rot. `8f4468d` korrigiert diese Annahmen.
- Lokal existiert zusätzlich `codex/pr56-conflict-resolution`, remote
  `fix/hold-short-press-recovery`. Der Tree des Branch-Heads `d27afd9` ist
  bitgenau identisch mit dem Squash-Merge `6bb8ec4`; der Branch enthält keine
  ungemergten Dateiinhalte.
- `.codex/config.toml` ist eine ungetrackte, maschinenspezifische Konfiguration
  und darf nicht in das Repository gelangen.
- GitHub meldet keine offenen PRs und keine offenen Issues.
- 25 historische Review-Threads sind ungelöst. Drei Befunde sind im aktuellen
  Code bereits behoben; die übrigen Befunde müssen gegen `main` einzeln
  verifiziert werden.

## Leitplanken

1. Keine reine Metadatenbereinigung: Ein Thread wird erst aufgelöst, wenn der
   Befund im aktuellen Code nachweislich behoben oder nachweislich nicht mehr
   anwendbar ist.
2. Jeder reale Verhaltensfehler folgt Red-Green-Refactor: Regressionstest
   schreiben, den erwarteten Fehlschlag beobachten, minimal beheben und den
   Test erneut ausführen.
3. Sicherheitsrelevante Befunde dürfen nicht durch schwächere Validierung,
   Fallbacks oder bloße Dokumentation ersetzt werden.
4. Keine Feature-Erweiterungen und keine fachfremden Refactorings.
5. Keine Secrets, Tokens oder private Konfigurationswerte in Tests, Logs,
   Commits oder Dokumentation aufnehmen.
6. Kein Force-Push. Rollbacks erfolgen ausschließlich über normale
   Revert-Commits.
7. `main` wird erst gepusht, wenn die vollständige lokale Verifikation grün ist.
8. Der Alt-Branch wird erst nach grünem Main-CI-Lauf und erneuter
   Tree-Gleichheitsprüfung gelöscht.

## Arbeitspakete

### Paket A: Lokale und CI-Hygiene

- `.codex/` ausschließlich lokal über `.git/info/exclude` ausblenden; die
  maschinenspezifische Datei weder tracken noch verändern.
- Die Entwicklungsabhängigkeiten aus `requirements-dev.txt` vollständig in der
  vorhandenen virtuellen Umgebung installieren, damit insbesondere die
  Pillow-abhängigen Tests nicht übersprungen werden.
- Commit `8f4468d` beibehalten und seine beiden ydotool-Regressionstests gegen
  den aktuellen Code verifizieren.

Akzeptanz:

- Die beiden zuvor roten ydotool-Tests bestehen.
- Die vollständige lokale Suite führt auch die 22 Pillow-abhängigen Tests aus.
- `git status --short` enthält keine ungetrackte `.codex/`-Datei.

### Paket B: Provider-, Konfigurations- und Fehlerhärtung

Zu prüfen und bei Bestätigung testgetrieben zu beheben:

- PR #7: Providerwechsel darf den OpenAI-Schlüssel nicht für OpenRouter
  wiederverwenden; leere Nicht-OpenAI-Endpunkte müssen abgelehnt werden.
- PR #10: Nicht-boolesche TTS-Einwilligungen dürfen nicht durch
  `bool(<string>)` wahr werden; veraltete Cloud-Ergebnisse dürfen nach Stop
  keinen Zustand mehr verändern.
- PR #17: Nicht-UTF-8-Konfigurationen müssen im Fallback kontrolliert behandelt
  werden; Datei-Permissions sind als Bits und nicht als Dezimalwert zu prüfen.
- PR #57: Migrierte unsichere Endpunkte dürfen nicht auf einen leeren oder
  impliziten OpenAI-Fallback fallen; die Live-Konfiguration darf erst nach
  erfolgreicher Endpunktvalidierung mutiert werden.
- PR #58: Unsanitisierte Providerfehler dürfen auch im Debug-Log nicht
  erscheinen.

Akzeptanz:

- Für jeden bestätigten Befund existiert ein gezielter Regressionstest.
- Ungültige oder unsichere Werte werden abgelehnt, ohne die letzte gültige
  Laufzeitkonfiguration zu verändern.
- Fehlerausgaben und Logs enthalten nur sanitisierten Text.

### Paket C: Laufzeit-, Clipboard- und Thread-Sicherheit

Zu prüfen und bei Bestätigung testgetrieben zu beheben:

- PR #13: Fehler beim Speichern eines Tray-Presets dürfen den UI-Pfad nicht
  unkontrolliert abbrechen.
- PR #38: CopyQ-Bereinigung muss in der fachlich korrekten Reihenfolge zum
  Clipboard-Restore erfolgen.
- PR #47: Qt-Clipboard-Zugriffe dürfen nicht unzulässig aus einem Worker-Thread
  erfolgen.
- PR #53: Voice-Routing muss einen bestehenden Draft erhalten; beim Schließen
  des Compose-Fensters während einer Aufnahme darf kein veraltetes Routingziel
  aktiv bleiben.
- PR #56: Nach einem verworfenen kurzen Hold ist der Debounce-Eintrag zu
  entfernen, sodass ein sofortiger korrigierender Tastendruck startet.

Akzeptanz:

- Nebenläufige oder verspätete Ergebnisse verändern keinen bereits beendeten
  Workflow.
- Clipboard- und UI-Operationen laufen im zulässigen Thread-Kontext.
- Ein kurzer Hold gefolgt von einem sofortigen zweiten Hold erzeugt zwei
  Startsignale und genau ein Discard-Signal.

### Paket D: UI-, i18n- und Prompt-Konsistenz

Zu prüfen und bei Bestätigung testgetrieben zu beheben:

- PR #14 und #15: Ein Sprachwechsel aktualisiert alle betroffenen Widgets,
  Main-Window-Labels und Tray-Aktionen vollständig.
- PR #44: Prompt-Anfragen werden durch die Preset-Absichtsregeln nicht in einen
  unbrauchbaren Text umgeschrieben.

Akzeptanz:

- Bestehende i18n-Tests decken alle aktualisierten Oberflächen und Aktionen ab.
- Der bekannte Prompt-Anfragefall bleibt als direkt nutzbarer Prompt erhalten.

### Paket E: Installation und Plattformdiagnose

Zu prüfen und bei Bestätigung test- beziehungsweise skriptgetrieben zu beheben:

- PR #40: Installationsskript-Tests dürfen nicht unkontrolliert als Root
  laufen oder dadurch falsche Ergebnisse liefern.
- PR #42: Wayland-Funktionalität wird über einen tatsächlich vorhandenen Socket
  geprüft und nicht nur über eine gesetzte Umgebungsvariable.
- PR #55: Die Installations-/Startanleitung verhindert eine parallele manuelle
  Instanz vor dem Start des User-Service.

Akzeptanz:

- Bash-Syntax- und vorhandene Installer-Tests bestehen.
- Die Diagnose unterscheidet gesetzte, aber nicht erreichbare Wayland-Sockets.
- Die dokumentierte Startreihenfolge verhindert Doppelinstanzen.

### Paket F: Bereits behobene Review-Befunde

Diese Threads werden gegen den aktuellen Code und vorhandene Tests verifiziert:

- PR #18: reservierter ffmpeg-Tempname wird nicht vorzeitig entfernt;
- PR #21: Pillow ist Bestandteil der Entwicklungsabhängigkeiten;
- PR #38: der Clipboard-Test mockt `_read_clipboard`.

Akzeptanz:

- Der aktuelle Code und mindestens ein passender Test belegen die Behebung.
- Erst danach werden die drei Threads auf GitHub als aufgelöst markiert.

## Review-Thread-Inventar

Alle folgenden Threads sind Bestandteil der Abschlussprüfung:

- #7: `PRRT_kwDOS8wgHs6KYgYS`, `PRRT_kwDOS8wgHs6KYgYY`
- #10: `PRRT_kwDOS8wgHs6K4Fz2`, `PRRT_kwDOS8wgHs6K4Fz8`
- #13: `PRRT_kwDOS8wgHs6K8fQe`
- #14: `PRRT_kwDOS8wgHs6LCGZn`
- #15: `PRRT_kwDOS8wgHs6LDJ6J`, `PRRT_kwDOS8wgHs6LDJ6K`
- #17: `PRRT_kwDOS8wgHs6LD4Z8`, `PRRT_kwDOS8wgHs6LD4Z-`
- #18: `PRRT_kwDOS8wgHs6LGSmR`
- #21: `PRRT_kwDOS8wgHs6LOHC1`
- #38: `PRRT_kwDOS8wgHs6NvFfM`, `PRRT_kwDOS8wgHs6NvFfP`
- #40: `PRRT_kwDOS8wgHs6N57G6`
- #42: `PRRT_kwDOS8wgHs6OVs5r`
- #44: `PRRT_kwDOS8wgHs6OV6KR`
- #47: `PRRT_kwDOS8wgHs6OdFwO`
- #53: `PRRT_kwDOS8wgHs6SZcCP`, `PRRT_kwDOS8wgHs6SZcCR`
- #55: `PRRT_kwDOS8wgHs6YAYC_`
- #56: `PRRT_kwDOS8wgHs6ZFzUk`
- #57: `PRRT_kwDOS8wgHs6drhy6`, `PRRT_kwDOS8wgHs6drhzA`
- #58: `PRRT_kwDOS8wgHs6dw0Pb`

## Commit- und Push-Strategie

- Jedes fachliche Paket erhält einen kleinen Conventional Commit.
- Der vorhandene Commit `8f4468d` bleibt als eigenständiger Testcommit erhalten.
- Vor dem Push werden alle Pakettests, die vollständige Testsuite,
  Compile-Check, Bash-Syntaxchecks, `git diff --check`, Secret-Scan und die
  Laufzeitdiagnose ausgeführt.
- Anschließend wird `main` einmalig ohne History-Rewrite gepusht.
- Der neue GitHub-Actions-Lauf wird bis zum terminalen Ergebnis überwacht.
  Ein roter Matrixjob wird anhand seiner Logs behoben und erneut verifiziert;
  die Bereinigung endet nicht bei einem bloßen Rerun.

## GitHub- und Branch-Abschluss

Nach einem vollständig grünen Main-CI-Lauf:

1. Alle 25 Threads erneut abfragen und nur die fachlich verifizierten Threads
   als aufgelöst markieren.
2. Bestätigen, dass weiterhin keine offenen PRs oder Issues existieren.
3. Erneut prüfen, dass `d27afd9` und `6bb8ec4` denselben Tree besitzen.
4. Remote-Branch `fix/hold-short-press-recovery` löschen.
5. Lokalen Branch `codex/pr56-conflict-resolution` löschen.
6. `git fetch origin --prune` ausführen.

## Abschlussverifikation

Die Zielbedingung ist erst erfüllt, wenn alle folgenden Nachweise gleichzeitig
vorliegen:

- `git status --short --branch` zeigt einen sauberen `main`, synchron mit
  `origin/main`;
- `git branch --format='%(refname:short)'` liefert ausschließlich `main`;
- die GitHub-Branchliste liefert ausschließlich `main`;
- offene PRs: 0;
- offene Issues: 0;
- ungelöste Review-Threads im Inventar: 0;
- aktueller regulärer Main-CI-Lauf: `completed/success`;
- keine laufenden oder wartenden Runs für den aktuellen Main-Commit;
- vollständige lokale Testsuite: 0 Fehler und keine durch fehlende
  Entwicklungsabhängigkeiten verursachten Skips;
- Compile-Check, Bash-Syntaxchecks, Secret-Scan, `git diff --check`,
  `git fsck --no-dangling` und Laufzeitdiagnose sind erfolgreich.

## Rollback und Abbruchregeln

- Vor dem Push können Paketcommits lokal mit normalen Git-Reverts
  zurückgenommen werden.
- Nach dem Push erfolgt jeder Rollback über einen neuen Revert-Commit.
- Bei einem echten, nicht sicher lösbaren Befund bleibt der zugehörige Thread
  ungelöst und die Bereinigung wird nicht als abgeschlossen bezeichnet.
- Bei einem roten CI-Lauf wird der konkrete Fehler behoben; Branch- und
  Thread-Löschungen warten bis zum grünen Lauf.
- Es werden weder Force-Push noch History-Rewrite eingesetzt.
