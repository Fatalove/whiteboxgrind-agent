"""Fixed container entry; host inputs are individually mounted read-only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

import yaml

from .runtime import WORK_ROOT


def _document(path):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 2:
        raise ValueError('schema_version 2 required')
    if not isinstance(value.get('target'), dict) or not isinstance(value.get('environment'), dict):
        raise ValueError('target and environment mappings required')
    if value['environment'].get('backend') != 'docker':
        raise ValueError('container requires an explicitly configured docker backend')
    return value


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == 'metadata':
        if len(args) != 2:
            raise ValueError('metadata requires exactly one mounted configuration')
        document = _document(args[1])
        target = document.get('target', {})
        print(json.dumps({'schema_version': 1, 'environment': document.get('environment'),
                          'target': {key: target.get(key) for key in ('source', 'sha256', 'fixture')}}))
        return 0
    if '--config' in args:
        index = args.index('--config') + 1
        if index >= len(args):
            raise ValueError('missing configuration path')
        original = Path(args[index])
        document = _document(original)
        request_root = WORK_ROOT / 'requests'
        request_root.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='request-', dir=request_root))
        (directory / 'host-requested-config.yaml').write_bytes(original.read_bytes())
        mounted = Path(os.environ.get('WBG_MOUNTED_SOURCE', '/inputs/source.c'))
        if mounted.parent != Path('/inputs') or not mounted.name.startswith('source'):
            raise ValueError('invalid individually mounted source path')
        document['target']['source'] = str(mounted)
        remapped = directory / 'mounted-config.json'
        remapped.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        args[index] = str(remapped)
        os.environ['WBG_ORIGINAL_CONFIG'] = str(original)
    from .cli import main as cli_main
    return cli_main(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(json.dumps({'schema_version': 1, 'status': 'error', 'reason_code': 'container_entry_error',
                          'detail': str(exc), 'execution': {'status': 'not_started'},
                          'recovery': {'status': 'not_attempted'}}))
        raise SystemExit(40)
