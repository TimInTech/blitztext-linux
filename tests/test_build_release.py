import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from scripts.build_release import build_release


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'; (root / 'app/assets').mkdir(parents=True)
    (root / 'app/__init__.py').write_text('__version__ = "1.2.3"\n')
    (root / 'app/blitztext_linux.py').write_text('pass\n')
    (root / 'app/assets/icon.svg').write_text('<svg/>')
    (root / 'run.sh').write_text('#!/bin/bash\n')
    (root / 'LICENSE').write_text('license')
    (root / 'app/__pycache__').mkdir()
    (root / 'app/__pycache__/x.pyc').write_text('cache')
    (root / 'secrets.env').write_text('PRIVATE=value')
    (root / '.venv').mkdir()
    return root


def test_package_contains_runtime_and_checksum_only(source, tmp_path):
    path = build_release(source, tmp_path / 'dist', 'v1.2.3')
    assert path.name == 'blitztext-linux-1.2.3.tar.gz'
    assert Path(str(path) + '.sha256').read_text() == hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
    with tarfile.open(path) as tar:
        names = tar.getnames()
        assert 'app/assets/icon.svg' in names and 'run.sh' in names
        assert not any('secret' in n or '.venv' in n or '__pycache__' in n for n in names)
        manifest = json.load(tar.extractfile('release.json'))
        assert manifest['version'] == '1.2.3'
        assert 'openai-whisper' in manifest['dependencies']
        assert manifest['torch'] == 'torch'
        assert tar.getmember('run.sh').mode == 0o755


@pytest.mark.parametrize('tag', ['v1.2.4', '1.2.3rc1', 'v01.2.3', '../../bad', '1' * 65])
def test_tag_must_match_version(source, tmp_path, tag):
    with pytest.raises(ValueError): build_release(source, tmp_path / 'dist', tag)


def test_refuses_symlink_in_runtime(source, tmp_path):
    (source / 'app/leak.py').symlink_to(source / 'secrets.env')
    with pytest.raises(ValueError): build_release(source, tmp_path / 'dist', 'v1.2.3')


def test_identical_sources_produce_identical_archive(source, tmp_path):
    first = build_release(source, tmp_path / 'first', 'v1.2.3').read_bytes()
    import time
    time.sleep(1.05)
    second = build_release(source, tmp_path / 'second', 'v1.2.3').read_bytes()
    assert first == second
