"""Export only key-free comparison metadata; leave native experiments unchanged."""
import argparse
import hashlib
import json
from pathlib import Path

from wbg import history


def export(work, destination, catalog):
    destination.mkdir(parents=True, exist_ok=False)

    def read(path):
        return json.loads(path.read_text()) if path.is_file() else {}

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')

    rows = []
    for run in sorted((work / 'runs').iterdir()):
        if not run.is_dir():
            continue
        row = history.summarize(run)
        row.update(catalog.get(run.name, {}))
        # A fixed allowlist excludes candidate, answer, key, command or raw trace fields.
        row = {key: row.get(key) for key in ('run_id', 'record_kind', 'status', 'reason_code',
               'execution', 'recovery', 'seed', 'trace_count')}
        if row['record_kind'] != 'analysis':
            continue
        original = read(run / 'effective-config.json')
        if not original:
            continue
        target = original.get('target', {})
        safe = {'target': {key: target[key] for key in ('sha256', 'fixture', 'adapter', 'abi') if key in target},
                'analysis': {key: original.get('analysis', {}).get(key) for key in ('method', 'model', 'selection_function') if key in original.get('analysis', {})},
                'environment': original.get('environment'),
                'inputs': {key: original.get('inputs', {}).get(key) for key in ('seed', 'trace_count', 'pilot_count')}}
        from wbg.config import ANALYSIS_DEFAULTS
        safe['analysis'] = {key: original.get('analysis', {})[key] for key in ANALYSIS_DEFAULTS
                            if key in original.get('analysis', {})}
        output = destination / 'runs' / run.name
        write(output / 'effective-config.json', safe)
        lock = read(run / 'source-lock.json')
        write(output / 'source-lock.json', {key: lock.get(key) for key in ('source_commits', 'patch_sha256', 'file_sha256')})
        resource = read(run / 'resource.json')
        write(output / 'resource.json', {key: resource.get(key) for key in ('compute_seconds', 'waiting_seconds', 'elapsed_seconds', 'rss_sum_sampled_max_bytes')})
        recovery = read(run / 'result.json').get('recovery', {})
        write(output / 'result.json', {'recovery': {'holdout_passed': recovery.get('holdout_passed') if isinstance(recovery, dict) else None}})
        rows.append(row)
    (destination / 'index.jsonl').write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    files = {str(path.relative_to(destination)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(destination.rglob('*')) if path.is_file()}
    record = {'schema_version': 1, 'scope': 'sanitized_native_history_snapshot', 'records': len(rows),
              'original_work_root': str(work), 'files': files,
              'snapshot_notice': 'Point-in-time comparison metadata; original native experiments retained; not a live shared store'}
    write(destination / 'manifest.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    args = parser.parse_args()
    result = export(args.work, args.destination, json.loads(args.catalog.read_text()))
    print(json.dumps({'records': result['records'], 'files': len(result['files'])}))
