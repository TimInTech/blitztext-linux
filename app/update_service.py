"""Anonymous, opt-in release updates. No GUI imports or work at construction time.

Installations are immutable directories. Only a fully provisioned installation
is published via ``releases/current``; ``previous`` retains the rollback target.
The caller must restart the application after install_release returns.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPOSITORY = 'TimInTech/blitztext-linux'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOAD_BASE = f'https://github.com/{REPOSITORY}/releases/download/'
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBERS = 10000
SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
REQUIREMENT = r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:(?:==|>=|<=|~=|>|<)[0-9][A-Za-z0-9.*+!-]*(?:,(?:==|>=|<=|~=|>|<)[0-9][A-Za-z0-9.*+!-]*)*)?'


class UpdateError(RuntimeError):
    """An update could not be checked or safely installed; current is unchanged."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str


def _version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(SEMVER, value):
        raise UpdateError('Expected a numeric stable version (MAJOR.MINOR.PATCH).')
    return tuple(int(part) for part in value.split('.'))


def _asset_url(url: str, version: str, suffix: str = '') -> bool:
    name = f'blitztext-linux-{version}.tar.gz{suffix}'
    return url in (f'{DOWNLOAD_BASE}{version}/{name}', f'{DOWNLOAD_BASE}v{version}/{name}')


def _allowed_url(url: str, *, redirect: bool = False) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    if parsed.fragment:
        return False
    if redirect and parsed.hostname in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
        return True
    if url == LATEST_URL:
        return True
    return bool(re.fullmatch(re.escape(DOWNLOAD_BASE) + 'v?' + SEMVER +
        r'/blitztext-linux-' + SEMVER + r'\.tar\.gz(?:\.sha256)?', url))


class _GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl, redirect=True):
            raise UpdateError('Release download redirected to an untrusted URL.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets):
            value = ast.literal_eval(node.value)
            _version(value)
            return value
    raise UpdateError('Release has no application version.')


class UpdateService:
    def __init__(self):
        # Deliberately lazy: constructing settings must never access network/disk.
        pass

    @property
    def releases_dir(self) -> Path:
        data = os.environ.get('XDG_DATA_HOME', '')
        base = Path(data) if data and Path(data).is_absolute() else Path.home() / '.local/share'
        return base / 'blitztext-linux/releases'

    @staticmethod
    def _supported():
        if os.environ.get('FLATPAK_ID') or Path('/.flatpak-info').exists():
            raise UpdateError('Flatpak updates are unsupported here; update through your Flatpak software manager.')

    def _fetch(self, url: str, limit: int) -> bytes:
        if not _allowed_url(url):
            raise UpdateError('Untrusted release URL.')
        request = urllib.request.Request(url, headers={
            'User-Agent': 'BlitztextLinux-Updater', 'Accept': 'application/vnd.github+json'
            if url == LATEST_URL else 'application/octet-stream',
        })
        deadline = time.monotonic() + 180
        # No credentials, cookies, git, or account configuration are consulted.
        opener = urllib.request.build_opener(_GitHubRedirect())
        with opener.open(request, timeout=20) as response:
            length = response.headers.get('Content-Length')
            if length is not None and (int(length) < 0 or int(length) > limit):
                raise UpdateError('Release response exceeds the download limit.')
            chunks = []; size = 0
            while True:
                if time.monotonic() > deadline:
                    raise UpdateError('Release download timed out.')
                chunk = response.read1(min(65536, limit - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise UpdateError('Release response exceeds the download limit.')
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise UpdateError('Incomplete release download.')
            return b''.join(chunks)

    def check_for_update(self, current_version: str) -> Release | None:
        self._supported()
        current = _version(current_version)
        try:
            try:
                payload = json.loads(self._fetch(LATEST_URL, 2 * 1024 * 1024))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                raise
            if not isinstance(payload, dict):
                raise UpdateError('Invalid release metadata.')
            if payload.get('draft') is True or payload.get('prerelease') is True:
                return None
            if payload.get('draft') is not False or payload.get('prerelease') is not False:
                raise UpdateError('Missing release stability metadata.')
            tag = payload.get('tag_name', '')
            version = tag[1:] if isinstance(tag, str) and tag.startswith('v') else tag
            if _version(version) <= current:
                return None
            assets = payload.get('assets')
            if not isinstance(assets, list):
                raise UpdateError('Missing release assets.')
            name = f'blitztext-linux-{version}.tar.gz'
            def asset_named(name, suffix, limit):
                matches = [a for a in assets if isinstance(a, dict) and a.get('name') == name]
                if len(matches) != 1:
                    raise UpdateError(f'Missing or ambiguous release asset: {name}')
                asset = matches[0]
                if (asset.get('state') != 'uploaded' or type(asset.get('size')) is not int
                        or not 0 < asset['size'] <= limit
                        or not _asset_url(asset.get('browser_download_url'), version, suffix)):
                    raise UpdateError('Invalid release asset URL, state, or size.')
                return asset
            asset = asset_named(name, '', MAX_ARCHIVE)
            digest = asset.get('digest')
            if digest is None:
                checksum = asset_named(name + '.sha256', '.sha256', 4096)
                content = self._fetch(checksum['browser_download_url'], 4096).decode('ascii')
                match = re.fullmatch(r'([a-fA-F0-9]{64}) [ *]' + re.escape(name) + r'\n?', content)
                if not match:
                    raise UpdateError('Invalid release checksum file.')
                sha256 = match[1].lower()
            elif isinstance(digest, str) and re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
                sha256 = digest[7:].lower()
            else:
                raise UpdateError('Release asset has no valid SHA256 digest.')
            return Release(version, asset['browser_download_url'], sha256)
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f'Could not check for an update: {exc}') from exc

    @staticmethod
    def _extract(data: bytes, destination: Path):
        # Bound the entire decompressed stream before tarfile parses PAX/GNU
        # metadata (those headers are processed before members are yielded).
        with tempfile.TemporaryFile() as raw:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                remaining = MAX_EXPANDED + MAX_MEMBERS * 1024
                while True:
                    chunk = compressed.read(min(65536, remaining + 1))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise UpdateError('Release archive exceeds the decompression limit.')
                    raw.write(chunk)
            raw.seek(0)
            with tarfile.open(fileobj=raw, mode='r:') as archive:
                UpdateService._extract_members(archive, destination)

    @staticmethod
    def _extract_members(archive, destination: Path):
        total = 0; seen = set()
        for count, member in enumerate(archive, 1):
            path = PurePosixPath(member.name)
            if (count > MAX_MEMBERS or member.size < 0 or
                    not member.name or path.is_absolute() or '..' in path.parts or
                    '\\' in member.name or str(path) != member.name.rstrip('/') or
                    path.parts[0] not in ('app', 'run.sh', 'release.json', 'LICENSE') or
                    member.name.rstrip('/') in seen or not (member.isfile() or member.isdir())):
                raise UpdateError('Unsafe release archive member.')
            seen.add(member.name.rstrip('/'))
            total += member.size
            if total > MAX_EXPANDED:
                raise UpdateError('Release archive exceeds the extraction limit.')
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                with target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=65536)
                target.chmod(0o755 if member.name == 'run.sh' else 0o644)

    @staticmethod
    def _manifest(path: Path, release: Release) -> dict:
        for name in ('run.sh', 'app/__init__.py', 'app/blitztext_linux.py', 'release.json'):
            if not (path / name).is_file():
                raise UpdateError(f'Release is missing {name}.')
        manifest = json.loads((path / 'release.json').read_text())
        if (manifest.get('schema') != 1 or manifest.get('version') != release.version
                or _read_version(path / 'app/__init__.py') != release.version):
            raise UpdateError('Release manifest/application version mismatch.')
        deps = manifest.get('dependencies')
        torch = manifest.get('torch')
        if (not isinstance(deps, list) or not deps or len(deps) > 100
                or not all(isinstance(d, str) and len(d) < 200 and re.fullmatch(REQUIREMENT, d) for d in deps)
                or not isinstance(torch, str) or not re.fullmatch(REQUIREMENT, torch)
                or re.split(r'[<>=~]', torch)[0] != 'torch'):
            raise UpdateError('Invalid release dependency manifest.')
        return manifest

    @staticmethod
    def _command(args: list[str], cwd: Path, timeout: int):
        # Exclude API secrets and pip/Python overrides from dependency processes.
        env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'XDG_CACHE_HOME') if k in os.environ}
        env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
                   PYTHONNOUSERSITE='1', QT_QPA_PLATFORM='offscreen')
        with subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, start_new_session=True) as process:
            try:
                _, error = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise UpdateError('Dependency provisioning timed out.') from exc
            if process.returncode:
                raise UpdateError('Dependency validation/provisioning failed: ' + error.decode(errors='replace')[-2000:])

    def _provision(self, path: Path, manifest: dict):
        # Fresh environment: pip never writes into the running application's venv.
        # Pip's shared wheel/download cache is intentionally retained (incl. Torch).
        self._command([sys.executable, '-I', '-m', 'venv', str(path / '.venv')], path, 120)
        python = str(path / '.venv/bin/python')
        pip = [python, '-I', '-m', 'pip', 'install', '--disable-pip-version-check',
               '--no-input', '--timeout', '20', '--retries', '2']
        self._command(pip + ['--index-url', 'https://download.pytorch.org/whl/cpu', manifest['torch']], path, 1800)
        self._command(pip + ['--index-url', 'https://pypi.org/simple', *manifest['dependencies']], path, 1800)
        self._command([python, '-I', '-m', 'pip', 'check'], path, 120)
        self._command([python, '-I', '-c',
            'import sys; sys.path.insert(0, sys.argv[1]); '
            'import PyQt6.QtWidgets, evdev, openai, torch, whisper, faster_whisper; '
            'import app.blitztext_linux', str(path)], path, 120)

    @staticmethod
    def _point(root: Path, name: str, target: Path):
        temporary = root / ('.pointer-' + uuid.uuid4().hex)
        try:
            temporary.symlink_to(target.name)
            os.replace(temporary, root / name)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _ready_target(root: Path, name: str) -> Path | None:
        pointer = root / name
        if not pointer.is_symlink():
            return None
        target = pointer.resolve()
        if target.parent == root.resolve() and (target / '.ready').is_file():
            return target
        return None

    def install_release(self, release: Release) -> Path:
        self._supported()
        _version(release.version)
        if (not _asset_url(release.url, release.version) or not isinstance(release.sha256, str)
                or not re.fullmatch(r'[a-fA-F0-9]{64}', release.sha256)):
            raise UpdateError('Invalid release URL or SHA256 digest.')
        staging = None
        try:
            root = self.releases_dir
            root.mkdir(parents=True, exist_ok=True)
            with (root / '.install.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise UpdateError('Another update installation is already running.') from exc
                data = self._fetch(release.url, MAX_ARCHIVE)
                if hashlib.sha256(data).hexdigest() != release.sha256.lower():
                    raise UpdateError('Release SHA256 checksum mismatch.')
                staging = root / (release.version + '-' + uuid.uuid4().hex)
                staging.mkdir(mode=0o700)
                self._extract(data, staging)
                manifest = self._manifest(staging, release)
                self._provision(staging, manifest)
                (staging / '.ready').write_text(release.version + '\n')
                previous = self._ready_target(root, 'current') or self._ready_target(root, 'previous')
                if previous:
                    self._point(root, 'previous', previous)
                self._point(root, 'current', staging)
                installed = staging
                staging = None
                return installed
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f'Could not install update: {exc}') from exc
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
