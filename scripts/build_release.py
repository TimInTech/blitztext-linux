#!/usr/bin/env python3
"""Build the dedicated updater asset and checksum, without git or dependencies.

Usage: python scripts/build_release.py --tag v0.9.0 --output dist
Edit DEPENDENCIES/TORCH when a future release changes its runtime requirements.
Only application code/assets, launcher, license and generated manifest ship.
"""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

DEPENDENCIES = ['PyQt6', 'evdev', 'openai', 'openai-whisper', 'faster-whisper']
TORCH = 'torch'
SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def build_release(source: Path, output: Path, tag: str) -> Path:
    source = Path(source); output = Path(output)
    version = tag[1:] if tag.startswith('v') else tag
    if not re.fullmatch(SEMVER, version):
        raise ValueError('Tag must be a stable numeric version, optionally prefixed with v.')
    tree = ast.parse((source / 'app/__init__.py').read_text())
    versions = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets)]
    if versions != [version]:
        raise ValueError('Release tag does not match app.__version__.')
    for required in ('app/blitztext_linux.py', 'run.sh', 'LICENSE'):
        if not (source / required).is_file():
            raise ValueError(f'Missing release file: {required}')
    files = [source / 'run.sh', source / 'LICENSE']
    for path in sorted((source / 'app').rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlinks may not be packaged: {path}')
        relative = path.relative_to(source / 'app')
        if '__pycache__' in relative.parts or any(p.startswith('.') for p in relative.parts):
            continue
        if path.is_file() and (path.suffix == '.py' or
                (relative.parts[0] == 'assets' and path.suffix in ('.svg', '.png', '.ico', '.jpg', '.webp'))):
            files.append(path)
    if any(p.is_symlink() for p in files) or (source / 'app').is_symlink():
        raise ValueError('Symlinks may not be packaged.')
    manifest = json.dumps(dict(schema=1, version=version, dependencies=DEPENDENCIES, torch=TORCH),
                          indent=2).encode() + b'\n'
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'blitztext-linux-{version}.tar.gz'
    with target.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as tar:
        for path in files:
            content = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(source).as_posix())
            info.size = len(content); info.mode = 0o755 if info.name == 'run.sh' else 0o644
            tar.addfile(info, io.BytesIO(content))
        info = tarfile.TarInfo('release.json'); info.size = len(manifest); info.mode = 0o644
        tar.addfile(info, io.BytesIO(manifest))
    Path(str(target) + '.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(build_release(args.source, args.output, args.tag))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
