"""Bind a newly built image to its actual engine bytes; never reuse native binary hashes."""
from importlib import metadata
import hashlib
import json
from pathlib import Path

project = Path('/opt/whiteboxgrind')
work = Path('/opt/wbg-engine')
native = json.loads(Path('/usr/share/whiteboxgrind/build/engine-inputs.json').read_text())
names = [name for name in native['file_names'] if name != 'src/whiteboxgrind/cpp/tracer.cpp']
names += ['src/whiteboxgrind/cpp/cpa.h']
record = {'recorded_on': '2026-10-28', 'scope': 'Actual container build bytes, independent of native binary identity',
          'backend': 'docker', 'work_root': str(work), 'distribution': 'Ubuntu-22.04',
          'source_commits': native['source_commits'], 'patch_sha256': native['patch_sha256'],
          'file_sha256': {name: hashlib.sha256((work / name).read_bytes()).hexdigest() for name in names},
          'python_packages': {name: metadata.version(name) for name in native['python_packages']}}
(work / 'baseline.json').write_text(json.dumps(record, indent=2) + '\n')
