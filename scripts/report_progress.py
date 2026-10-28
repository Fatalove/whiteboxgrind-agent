"""Read-only Agent-facing presentation. Does not change supervisor decisions or limits."""
import argparse
import json
from pathlib import Path
from statistics import median


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default


def identity(config):
    # Seed is intentionally excluded; target, method and scale must match exactly.
    return {k: config[k] for k in ('target', 'environment', 'analysis')} | {
        'inputs': {k: v for k, v in config['inputs'].items() if k != 'seed'}}


def source_identity(lock):
    return sorted((r['path'], r['sha256']) for r in lock['files'])


def history(run, evidence):
    config = read(run / 'effective-config.json')
    lock = read(run / 'orchestrator-lock.json')
    records = []
    for path in sorted(evidence.glob('seed*/completion-audit.json')):
        audit = read(path)
        # No self-calibration or using a later experiment to backdate a quote.
        if audit['run_id'] >= run.name:
            continue
        if (audit['status'] != 'verified' or audit['manifest_mismatches'] or
                not audit['runtime_matches_frozen_implementation']):
            continue
        other = read(path.parent / 'effective-config.json')
        snapshot = read(path.parent / 'orchestrator-lock.json')
        if not other or not snapshot or identity(config) != identity(other) or source_identity(lock) != source_identity(snapshot):
            continue
        comparison = audit.get('estimate_comparison', {})
        value = comparison.get('post_confirmation_compute_seconds')
        if value is None or not comparison.get('timing_basis', '').startswith('same-boot completion observer'):
            continue  # Never substitute total time (including pilot/wait) or rough cross-boot timing.
        records.append({'run_id': audit['run_id'], 'seconds': value})
    return records


def report(view, records):
    status = view.get('status', 'unknown')
    progress = view.get('progress') or {}
    result = {'status': status, 'progress': progress, 'remaining_compute_seconds': None,
              'estimate_quality': 'unknown', 'recovery_guaranteed': False}
    terminal = status in {'verified', 'no_key', 'probe_completed', 'error', 'unsupported', 'cancelled', 'resource_limit'}
    at_start = progress.get('stage') == 'awaiting_formal_approval'
    if not terminal and at_start and records:
        result.update(remaining_compute_seconds=round(median(r['seconds'] for r in records)),
                      estimate_quality='limited_local_history', reference_runs=[r['run_id'] for r in records],
                      observed_seconds={'min': min(r['seconds'] for r in records),
                                        'max': max(r['seconds'] for r in records)})
    # In-flight samples have no reliable substage completion timestamp here.
    # Preserve raw estimates internally; don't make a precise-looking countdown.
    if not terminal:
        space = view.get('space', {})
        result['disk_storage'] = {'estimated_additional_bytes': space.get('estimated_additional_bytes'),
                                 'current_work_file_bytes': view.get('observations', {}).get('logical_output_bytes'),
                                 'basis': 'conservative work-file estimate; physical allocation may differ'}
        if space.get('estimate_exceeds_allowance'):
            result['action_required'] = 'disk_storage_choice_needed'
    return result


def render(value):
    p = value['progress']
    lines = [f"当前状态：{value['status']}；阶段：{p.get('stage') or '未知'}。"]
    if p.get('completed') is not None and p.get('total') is not None:
        lines.append(f"已确认完成 {p['completed']}/{p['total']} 条。")
    seconds = value['remaining_compute_seconds']
    if seconds is not None:
        lines.append(f"预计还需约 {seconds / 60:.1f} 分钟完成本次分析与独立验证（依据 {len(value['reference_runs'])} 次匹配实测；样本少，可能偏差）。")
    elif 'disk_storage' in value:
        lines.append('剩余时间暂无法可靠估计。')
    disk = value.get('disk_storage', {}).get('estimated_additional_bytes')
    if disk is not None:
        lines.append(f"预计新增硬盘占用约 {disk / 2**30:.1f} GiB（保守文件大小估计）。")
    current = value.get('disk_storage', {}).get('current_work_file_bytes')
    if current is not None:
        lines.append(f"当前任务硬盘文件约 {current / 2**30:.1f} GiB。")
    if value.get('action_required'):
        lines.append('预计硬盘需求超出已批准范围，需要选择后才能继续。')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True, help='native run directory named by run ID')
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = read(args.run_dir / 'result.json')
    if result:
        view = {'status': result['status'], 'progress': {'stage': result.get('completed_stage')}}
    else:
        view = read(args.run_dir / 'progress.json') or {
            'status': 'running', 'progress': read(args.run_dir / 'stage.json', {})}
        if view.get('progress', {}).get('stage') == 'probe-collect':
            view['progress'].update(completed=0, total=1)
        view['observations'] = {'logical_output_bytes': sum(
            p.stat().st_size for p in args.run_dir.rglob('*') if p.is_file())}
    value = report(view, history(args.run_dir, args.evidence_root))
    print(json.dumps(value, ensure_ascii=False) if args.json else render(value))


if __name__ == '__main__':
    main()
