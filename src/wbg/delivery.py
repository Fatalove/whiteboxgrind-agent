"""User-facing recovery record; no reference-key input."""
import hashlib
import json
from pathlib import Path
from .protocol import atomic_json


def recovery(run: Path, result: dict) -> dict:
    candidate_path=run/'candidate.json'
    candidate=json.loads(candidate_path.read_text()) if candidate_path.is_file() else {}
    validation_path=run/'validation.json'
    validation=json.loads(validation_path.read_text()) if validation_path.is_file() else {}
    cfg_path=run/'effective-config.json'
    cfg=json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    key=candidate.get('key_hex')
    provenance=False
    if key is not None:
        if not isinstance(key,str) or len(key)!=32 or len(bytes.fromhex(key))!=16:
            raise ValueError('invalid AES-128 candidate')
        csv=run/'cpa.csv'
        provenance=csv.is_file() and hashlib.sha256(csv.read_bytes()).hexdigest()==candidate.get('cpa_csv_sha256')
        if not provenance:
            raise ValueError('candidate CPA provenance mismatch')
    verified=bool(key and provenance and result.get('status')=='verified' and validation.get('verified')
                  and validation.get('passed_count')==16 and validation.get('holdout_count')==16
                  and validation.get('verifier_selftest_passed')
                  and validation.get('candidate_sha256')==hashlib.sha256(candidate_path.read_bytes()).hexdigest())
    if result.get('status')=='verified' and not verified:
        raise ValueError('verified result lacks independent candidate evidence')
    record={'schema_version':1,'run_id':result['run_id'],'algorithm':'AES-128',
            'key_type':'aes128_master_key','encoding':'hex','length_bytes':16,
            'status':'verified' if verified else 'candidate' if key else 'not_recovered',
            'key_hex':key,'target_sha256':cfg.get('target',{}).get('sha256'),
            'method':cfg.get('analysis'),
            'candidate_source':{'kind':'this_run_cpa','sha256':candidate.get('cpa_csv_sha256')} if key else None,
            'validation':{'passed':validation.get('passed_count'),'total':validation.get('holdout_count'),
                          'verified':verified},
            'boundary':'16 个独立留出验证是本次实测证据，不是对所有输入的数学证明；密钥不自动等于赛题 flag 或业务口令。'}
    atomic_json(run/'recovery.json',record)
    return record


def report(run: Path,result: dict,record: dict) -> str:
    return (f"# Whiteboxgrind Agent 分析结果\n\n运行：`{result['run_id']}`\n\n"
            f"- 终态：`{result['status']}`；原因：`{result.get('reason_code') or 'none'}`\n"
            f"- 目标 SHA256：`{record.get('target_sha256') or 'unknown'}`\n"
            f"- 密钥状态：`{record['status']}`\n"
            f"- AES-128 主密钥（16 字节，32 位十六进制）：`{record['key_hex'] or '未恢复'}`\n"
            f"- 独立留出验证：`{record['validation']['passed']}/{record['validation']['total']}`\n\n"
            "先读 recovery.json 和 validation.json；evidence 保存 CPA 来源、配置、输入输出及校验记录，logs 保存执行日志。\n\n"
            +record['boundary']+"\n\n## 数据保留选择\n\n"
            "全部原始数据默认保留。请在任务结束后选择：全部保留、保留复核包，或仅保留精简结果。"
            "精简结果将失去完整复核能力；未回复不会删除。清理必须先生成本运行的清单，再根据你的选择执行。\n")
