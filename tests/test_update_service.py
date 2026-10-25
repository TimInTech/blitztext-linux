from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.error import HTTPError

import pytest

from app import update_service as u

URL = 'https://github.com/TimInTech/blitztext-linux/releases/download/v1.2.0/blitztext-linux-1.2.0.tar.gz'


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.delenv('FLATPAK_ID', raising=False)
    return u.UpdateService()


def metadata(**changes):
    result = dict(tag_name='v1.2.0', draft=False, prerelease=False, assets=[dict(
        name='blitztext-linux-1.2.0.tar.gz', browser_download_url=URL,
        digest='sha256:' + 'a' * 64, size=100, state='uploaded')])
    result.update(changes)
    return result


def serve(monkeypatch, payload):
    monkeypatch.setattr(u.UpdateService, '_fetch', lambda self, url, limit: json.dumps(payload).encode())


def archive(extra=None, version='1.2.0'):
    files = {'app/__init__.py': f'__version__ = "{version}"\n'.encode(),
             'app/blitztext_linux.py': b'pass\n', 'run.sh': b'#!/bin/bash\n',
             'release.json': json.dumps(dict(schema=1, version=version,
                 dependencies=['PyQt6', 'evdev', 'openai', 'openai-whisper', 'faster-whisper'],
                 torch='torch')).encode()}
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name); info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        if extra:
            tar.addfile(extra, io.BytesIO(b'x' * extra.size))
    return data.getvalue()


def install_fixture(service, monkeypatch, data):
    monkeypatch.setattr(service, '_fetch', lambda url, limit: data)
    def provision(path, manifest):
        python = path / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexit 0\n'); python.chmod(0o755)
    monkeypatch.setattr(service, '_provision', provision)
    return u.Release('1.2.0', URL, hashlib.sha256(data).hexdigest())


def test_latest_release_numeric_comparison(service, monkeypatch):
    serve(monkeypatch, metadata())
    assert service.check_for_update('1.1.99') == u.Release('1.2.0', URL, 'a' * 64)
    assert service.check_for_update('1.10.0') is None
    assert service.check_for_update('1.2.0') is None


@pytest.mark.parametrize('version', ['01.2.0', '1.2', '1.2.0rc1', '1.2.0+build', '１.2.0', '../1.2.0'])
def test_strict_versions(service, monkeypatch, version):
    serve(monkeypatch, metadata(tag_name=version))
    with pytest.raises(u.UpdateError): service.check_for_update('0.9.0')


@pytest.mark.parametrize('flag', ['draft', 'prerelease'])
def test_unstable_is_not_offered(service, monkeypatch, flag):
    serve(monkeypatch, metadata(**{flag: True}))
    assert service.check_for_update('0.9.0') is None


@pytest.mark.parametrize('change', [dict(digest=None), dict(digest='sha256:bad'),
    dict(browser_download_url='https://evil.example/payload'), dict(size=10**12)])
def test_missing_integrity_or_bad_asset_rejected(service, monkeypatch, change):
    payload = metadata(); payload['assets'][0].update(change); serve(monkeypatch, payload)
    with pytest.raises(u.UpdateError): service.check_for_update('0.9.0')


def test_checksum_fallback(service, monkeypatch):
    payload = metadata(); payload['assets'][0]['digest'] = None
    checksum_url = URL + '.sha256'
    payload['assets'].append(dict(name='blitztext-linux-1.2.0.tar.gz.sha256',
        browser_download_url=checksum_url, size=100, state='uploaded'))
    monkeypatch.setattr(service, '_fetch', lambda url, limit: json.dumps(payload).encode()
        if url == u.LATEST_URL else (('b' * 64) + '  blitztext-linux-1.2.0.tar.gz\n').encode())
    assert service.check_for_update('0.9.0').sha256 == 'b' * 64


def test_not_found_is_no_update_but_rate_limit_is_error(service, monkeypatch):
    def fail(url, limit): raise HTTPError(url, 404, 'missing', {}, None)
    monkeypatch.setattr(service, '_fetch', fail)
    assert service.check_for_update('0.9.0') is None
    def limited(url, limit): raise HTTPError(url, 403, 'rate limit', {}, None)
    monkeypatch.setattr(service, '_fetch', limited)
    with pytest.raises(u.UpdateError): service.check_for_update('0.9.0')


def test_installs_and_keeps_prior_release(service, monkeypatch):
    release = install_fixture(service, monkeypatch, archive())
    first = service.install_release(release)
    second = service.install_release(release)
    root = service.releases_dir
    assert (root / 'current').resolve() == second
    assert (root / 'previous').resolve() == first
    assert first.is_dir() and (second / '.ready').is_file()
    assert (second / 'app/__init__.py').read_text() == '__version__ = "1.2.0"\n'


@pytest.mark.parametrize('kind', ['digest', 'provision', 'version'])
def test_failure_preserves_current(service, monkeypatch, kind):
    release = install_fixture(service, monkeypatch, archive())
    first = service.install_release(release)
    if kind == 'digest': release = u.Release('1.2.0', URL, '0' * 64)
    elif kind == 'version': release = install_fixture(service, monkeypatch, archive(version='9.0.0'))
    else:
        def fail(*args): raise OSError('dependency failure')
        monkeypatch.setattr(service, '_provision', fail)
    with pytest.raises(u.UpdateError): service.install_release(release)
    assert (service.releases_dir / 'current').resolve() == first
    assert len([p for p in service.releases_dir.iterdir() if p.is_dir() and not p.is_symlink()]) == 1


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
    ('app/link', tarfile.SYMTYPE), ('app/hard', tarfile.LNKTYPE), ('app/dev', tarfile.CHRTYPE),
    ('.venv/bin/python', tarfile.REGTYPE), ('app/__init__.py', tarfile.REGTYPE)])
def test_unsafe_archives_rejected(service, monkeypatch, name, kind):
    info = tarfile.TarInfo(name); info.type = kind; info.linkname = '/tmp/escape'
    release = install_fixture(service, monkeypatch, archive(info))
    with pytest.raises(u.UpdateError): service.install_release(release)
    assert not (service.releases_dir / 'current').exists()


def test_flatpak_is_explicit_error(service, monkeypatch):
    monkeypatch.setenv('FLATPAK_ID', 'io.github.TimInTech.Blitztext')
    with pytest.raises(u.UpdateError, match='Flatpak'): service.check_for_update('0.9.0')
    with pytest.raises(u.UpdateError, match='Flatpak'): service.install_release(u.Release('1.2.0', URL, 'a' * 64))


def test_install_does_not_accept_arbitrary_url(service):
    with pytest.raises(u.UpdateError):
        service.install_release(u.Release('1.2.0', 'https://evil.example/payload', 'a' * 64))


def test_download_limit_and_no_auth(service, monkeypatch):
    class Response(io.BytesIO):
        headers = {}
    class Opener:
        def open(self, request, timeout):
            assert not request.has_header('Authorization')
            assert timeout <= 30
            return Response(b'12345')
    monkeypatch.setattr(u.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(u.UpdateError): service._fetch(u.LATEST_URL, 4)


def test_redirect_rejects_non_github_host():
    handler = u._GitHubRedirect()
    request = u.urllib.request.Request(URL)
    for target in ['http://release-assets.githubusercontent.com/file', 'https://evil.example/x',
                   'https://github.com/other/repo/file', 'https://user@release-assets.githubusercontent.com/file']:
        with pytest.raises(u.UpdateError): handler.redirect_request(request, None, 302, '', {}, target)


def test_constructor_is_inert_even_when_flatpak(service, monkeypatch):
    monkeypatch.setenv('FLATPAK_ID', 'test')
    def forbidden(*args, **kwargs): raise AssertionError('construction performed IO')
    monkeypatch.setattr(Path, 'exists', forbidden)
    monkeypatch.setattr(u.urllib.request, 'build_opener', forbidden)
    u.UpdateService()


def test_concurrent_install_is_rejected_without_changing_current(service, monkeypatch):
    release = install_fixture(service, monkeypatch, archive())
    first = service.install_release(release)
    with (service.releases_dir / '.install.lock').open('a') as lock:
        u.fcntl.flock(lock, u.fcntl.LOCK_EX | u.fcntl.LOCK_NB)
        with pytest.raises(u.UpdateError, match='already running'):
            u.UpdateService().install_release(release)
    assert (service.releases_dir / 'current').resolve() == first


def test_failed_pointer_switch_preserves_current(service, monkeypatch):
    release = install_fixture(service, monkeypatch, archive())
    first = service.install_release(release)
    replace = u.os.replace
    def fail_current(src, dst):
        if Path(dst).name == 'current': raise OSError('failed atomic switch')
        replace(src, dst)
    monkeypatch.setattr(u.os, 'replace', fail_current)
    with pytest.raises(u.UpdateError): service.install_release(release)
    assert (service.releases_dir / 'current').resolve() == first
    assert not list(service.releases_dir.glob('.pointer-*'))


@pytest.mark.parametrize('limit', ['MAX_EXPANDED', 'MAX_MEMBERS'])
def test_extraction_limits_preserve_current(service, monkeypatch, limit):
    release = install_fixture(service, monkeypatch, archive())
    first = service.install_release(release)
    monkeypatch.setattr(u, limit, 1)
    with pytest.raises(u.UpdateError): service.install_release(release)
    assert (service.releases_dir / 'current').resolve() == first


def test_truncated_download_and_timeout_are_errors(service, monkeypatch):
    class Response(io.BytesIO):
        headers = {'Content-Length': '8'}
    class Opener:
        def open(self, request, timeout): return Response(b'abc')
    monkeypatch.setattr(u.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(u.UpdateError): service.check_for_update('0.9.0')
    def fail(*args): raise TimeoutError('timeout')
    monkeypatch.setattr(service, '_fetch', fail)
    with pytest.raises(u.UpdateError): service.check_for_update('0.9.0')


def test_dependency_commands_have_clean_environment_and_fail_safely(service, tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-secret')
    monkeypatch.setenv('PIP_EXTRA_INDEX_URL', 'https://example.invalid')
    service._command([sys.executable, '-c',
        'import os, pathlib; assert "OPENAI_API_KEY" not in os.environ; '
        'assert "PIP_EXTRA_INDEX_URL" not in os.environ; '
        'pathlib.Path("ran").write_text("yes")'], tmp_path, 10)
    assert (tmp_path / 'ran').read_text() == 'yes'
    with pytest.raises(u.UpdateError):
        service._command([sys.executable, '-c', 'raise SystemExit(1)'], tmp_path, 10)
    with pytest.raises(u.UpdateError, match='timed out'):
        service._command([sys.executable, '-c', 'import time; time.sleep(20)'], tmp_path, 0.05)


def test_provision_never_uses_existing_environment(service, tmp_path, monkeypatch):
    """Run real venv creation, replace only network-dependent pip/import commands."""
    path = tmp_path / 'new-release'; path.mkdir()
    real_command = service._command
    calls = []
    def offline(args, cwd, timeout):
        if 'venv' in args:
            real_command(args, cwd, timeout)
        else:
            # Every mutating pip command must point into the new environment.
            assert args[0] == str(path / '.venv/bin/python')
            calls.append(args)
    monkeypatch.setattr(service, '_command', offline)
    service._provision(path, dict(torch='torch', dependencies=['PyQt6', 'openai']))
    assert (path / '.venv/pyvenv.cfg').is_file()
    assert any('https://download.pytorch.org/whl/cpu' in args for args in calls)
    assert any('PyQt6' in args and 'openai' in args for args in calls)
    assert any('check' in args for args in calls)


def test_build_install_round_trip(service, tmp_path, monkeypatch):
    from scripts.build_release import build_release
    source = Path(__file__).resolve().parents[1]
    from app import __version__
    package = build_release(source, tmp_path / 'dist', 'v' + __version__)
    install_fixture(service, monkeypatch, package.read_bytes())
    url = f'https://github.com/TimInTech/blitztext-linux/releases/download/v{__version__}/{package.name}'
    path = service.install_release(u.Release(__version__, url, hashlib.sha256(package.read_bytes()).hexdigest()))
    assert (path / 'app/update_service.py').is_file()
    assert (path / 'run.sh').stat().st_mode & 0o111


def test_gzip_expansion_is_bounded_before_tar_metadata(service, monkeypatch):
    import gzip
    # A huge PAX header must not bypass the member-size check inside tarfile.
    monkeypatch.setattr(u, 'MAX_EXPANDED', 1024)
    info = tarfile.TarInfo('metadata')
    info.type = tarfile.XHDTYPE
    info.size = 10 * 1024 * 1024
    payload = gzip.compress(info.tobuf() + b' ' * info.size)
    release = install_fixture(service, monkeypatch, payload)
    with pytest.raises(u.UpdateError, match='limit'):
        service.install_release(release)


def test_constructor_does_not_create_data_directory(tmp_path, monkeypatch):
    data = tmp_path / 'not-created'
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    u.UpdateService()
    assert not data.exists()
