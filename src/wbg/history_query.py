"""Comparable local history for an Agent; never return candidate or raw trace data."""
import json
import os
from pathlib import Path

from . import config, execution, history
from .runtime import BACKEND, ENGINE_ROOT


def _read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default


def _target(target):
    if target.get('sha256'):
        return ('sha256', target['sha256'], target.get('adapter'), target.get('abi'))
    if target.get('fixture'):
        return ('fixture', target['fixture'], target.get('adapter'), target.get('abi'))
    return None  # Unknown identities must never become an apparent match.


def _engine(lock):
    if not lock:
        return None
    return {'source_commits': lock.get('source_commits'), 'patch_sha256': lock.get('patch_sha256'),
            'file_sha256': lock.get('file_sha256')}


def query(effective, limit=5, *, work=None, data=None, project=None):
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('history limit must be an integer from 1 to 5')
    work = work or execution.WORK
    project = project or config.PROJECT
    data = data or (work / 'history-data' if BACKEND == 'docker' else project.parent / 'Whiteboxgrind-data')
    catalog = _read(project / 'experiments/run-catalog.json', {})
    index = data / 'history/index.jsonl'
    history.rebuild(work / 'runs', index, work / 'active.json', catalog)
    baseline = ENGINE_ROOT / 'baseline.json' if BACKEND == 'docker' else project / 'experiments/locks/stage-b-environment.json'
    current_engine = _engine(_read(baseline))
    rows = [(work / 'runs', json.loads(line)) for line in index.read_text().splitlines()]
    prior = os.environ.get('WBG_PRIOR_HISTORY') if BACKEND == 'docker' else None
    if prior:
        prior_root = Path(prior)
        record = _read(prior_root / 'manifest.json', {})
        if record.get('schema_version') != 1 or record.get('scope') != 'sanitized_native_history_snapshot':
            raise ValueError('invalid prior history snapshot')
        import hashlib
        for name, expected in record['files'].items():
            path = (prior_root / name).resolve()
            if not path.is_relative_to(prior_root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('prior history snapshot integrity mismatch')
        rows += [(prior_root / 'runs', json.loads(line)) for line in (prior_root / 'index.jsonl').read_text().splitlines()]
    matches = []
    seen = set()
    for runs, row in rows:
        if row['run_id'] in seen:
            raise ValueError('duplicate run identity across history stores')
        seen.add(row['run_id'])
        if row.get('record_kind') != 'analysis':
            continue
        root = runs / row['run_id']
        old = _read(root / 'effective-config.json', {})
        target = _target(effective['target'])
        if target is None or target != _target(old.get('target', {})):
            continue
        if old.get('analysis') != effective['analysis']:
            continue
        inputs = old.get('inputs', {})
        engine = _engine(_read(root / 'source-lock.json'))
        comparison = {'same_target': True, 'same_analysis': True,
                      'same_formal_count': inputs.get('trace_count') == effective['inputs']['trace_count'],
                      'same_pilot_count': inputs.get('pilot_count') == effective['inputs']['pilot_count'],
                      'same_engine': engine == current_engine if engine and current_engine else None,
                      'same_backend': old.get('environment') == effective['environment'],
                      'hardware_match': None}
        # Different engines/scales remain visible with explicit limited transferability.
        score = sum(comparison[k] is True for k in ('same_formal_count', 'same_pilot_count', 'same_engine', 'same_backend'))
        resource = _read(root / 'resource.json', {})
        result = _read(root / 'result.json', {})
        recovery = result.get('recovery', {})
        item = {k: row.get(k) for k in ('run_id', 'status', 'reason_code', 'execution', 'recovery', 'seed', 'trace_count')}
        item.update(comparison=comparison, evidence_root=str(root),
                    holdout_passed=recovery.get('holdout_passed') if isinstance(recovery, dict) else None,
                    internal_measurements={k: resource.get(k) for k in ('compute_seconds', 'waiting_seconds', 'elapsed_seconds', 'rss_sum_sampled_max_bytes')},
                    transferability='same configured target and method; inspect scale, engine and hardware differences')
        if prior and runs == Path(prior) / 'runs':
            item['comparison_snapshot_root'] = str(root)
            item['evidence_root'] = str(Path(record['original_work_root']) / 'runs' / row['run_id'])
            item['history_storage'] = 'sanitized point-in-time metadata; original native evidence retained separately'
        matches.append((score, row['run_id'], item))
    matches.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return {'schema_version': 1, 'command': 'history query', 'status': 'ok',
            'matched_analysis_records': len(matches), 'returned': min(limit, len(matches)),
            'records': [row[2] for row in matches[:limit]],
            'scope': 'success and failure evidence; diagnostics excluded; no recovery guarantee; hardware match unknown unless separately verified'}
