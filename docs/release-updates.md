# Release updates

Blitztext checks public stable releases from `TimInTech/blitztext-linux` only when
requested in **Settings → Updates**. It sends no GitHub authentication. A release
must have a numeric `X.Y.Z` version (optional `v` prefix on its tag) newer than the
running app; drafts and prereleases are not offered.

## Publishing a compatible release

1. Set `app.__version__` in `app/__init__.py` to the release version.
2. Commit the intended application and tag that commit `vX.Y.Z` (replace `X.Y.Z`
   with that version). Publish a stable GitHub release for the tag.
3. `.github/workflows/release.yml` builds and uploads
   `blitztext-linux-X.Y.Z.tar.gz` and the matching `.tar.gz.sha256` file. The job
   refuses a version/tag mismatch. Publishing assets requires the workflow's
   repository-scoped GitHub token; end users need no token or GitHub account.

A manual workflow run builds artifacts for an existing tag without publishing
assets. To test the current version locally:

```bash
python3 scripts/build_release.py --tag "v$(python3 -c 'from app import __version__; print(__version__)')" --output /tmp/blitztext-release-check
(cd /tmp/blitztext-release-check && sha256sum --check *.sha256)
```

The archive contains application code/assets, `run.sh`, `LICENSE` and a generated
`release.json`. It excludes Git data, local configuration, credentials, tests and
the development environment. Runtime dependency requirements live in
`scripts/build_release.py`; update them when a release requires new dependencies.
An existing public release without these assets cannot be installed by the updater.
The updater uses GitHub's asset SHA256 digest, falling back to the attached
checksum file when GitHub provides no digest. This checks integrity against the
publisher's GitHub release; it is not an independent publisher signature.

## Installation and startup

The updater downloads over HTTPS with size and time limits, checks SHA256, and
rejects archive traversal, links and special files. It installs into a unique
version directory below `${XDG_DATA_HOME:-~/.local/share}/blitztext-linux/releases`.
Only absolute `XDG_DATA_HOME` values are used; relative values use the home fallback.
A process lock prevents concurrent installations.

Each release receives a separate Python virtual environment. CPU-only Torch is
installed first, then the manifest's dependencies from PyPI. Pip's cache is reused;
the running app's environment is not modified. Dependency checks and imports must
succeed before a `.ready` marker is written and the `current` symlink is switched
atomically. The old managed release is retained through `previous`. Download,
checksum, extraction or preparation errors leave `current` unchanged.

A first update can require substantial disk space and download time for the Python
runtime dependencies. System packages remain the responsibility of the initial
installer. An update cannot silently install new apt packages or repair missing
host libraries. Settings, credentials, history and Whisper model caches stay in
their existing locations.

The installed service continues to invoke the original checkout's `run.sh`.
That launcher selects the ready managed release at the next start; an incomplete
or broken pointer falls back to `previous`, then the original checkout. Launching
`app/blitztext_linux.py` directly bypasses this selection. Application failures
after successful startup are not automatically rolled back.

Close and reopen Settings to view an ongoing update; its state belongs to the
application. After success, quit and restart Blitztext. No live files are replaced
inside the running app. Existing versions without this updater need one initial
upgrade through their previous installation method. Flatpak uses its own package
manager and does not install these archives.

## Recovery

Quit Blitztext before changing release pointers. To select the retained previous
managed release:

```bash
python3 - <<'PY'
import os
from pathlib import Path
base = Path(os.environ.get('XDG_DATA_HOME', ''))
if not base.is_absolute():
    base = Path.home() / '.local/share'
root = base / 'blitztext-linux/releases'
previous = root / 'previous'
if not previous.is_symlink():
    raise SystemExit('No previous managed release is available.')
target = previous.resolve()
if target.parent != root.resolve() or not (target / '.ready').is_file():
    raise SystemExit('Previous release is not ready.')
pointer = root / '.rollback-current'
pointer.symlink_to(target.name)
os.replace(pointer, root / 'current')
print('Previous release selected. Restart Blitztext.')
PY
```

Before the first managed update there is no `previous` managed release. To return
to the original checkout, quit Blitztext and remove only the `current` and
`previous` symlinks in the releases directory, then launch the original `run.sh`.
The release directories and original checkout are retained. Old release
directories can be removed manually once they are neither running nor selected by
`current`/`previous`; the updater does not delete previous installations for you.

API reference: [GitHub REST releases](https://docs.github.com/en/rest/releases/releases).
