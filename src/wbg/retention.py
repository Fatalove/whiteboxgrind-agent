"""Explicit terminal-run cleanup, bound to a hashed plan and user choice."""
from __future__ import annotations
import fcntl
import hashlib
import json
from pathlib import Path
import re
import secrets

from .protocol import EXIT, atomic_json

ESSENTIAL={'result.json','recovery.json','report.md','validation.json','accounting.json',
           'budget-group.json','operation.json','locations.json','source-lock.json',
           'effective-config.json','requested-config.json','effective-config.yaml','requested-config.yaml',
           'target-provenance.json','orchestrator-lock.json','formal-authorized.json',
           'budget-extensions.json','boundary-state.json','manifest.json','retention.json'}

def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def _files(root):
    if root.is_symlink(): raise ValueError('symlink root refused')
    result=[]
    for p in sorted(root.rglob('*')):
        if p.is_symlink(): raise ValueError('symlink inside run refused')
        if p.is_file():
            result.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':_hash(p)})
    return result

def _keep(path,policy):
    if policy=='all': return True
    p=Path(path)
    if len(p.parts)==1 and (path in ESSENTIAL or path.endswith('.json') and path not in {'candidate.json'}): return True
    if p.parts[0]=='decisions': return True
    if policy=='minimal': return False
    if path in {'candidate.json','cpa.csv','holdout-ciphertexts.bin'}: return True
    if p.parts[0] in {'inputs','logs','orchestrator'}: return True
    if p.parts[0]=='target' and p.suffix in {'.c','.h','.json'}: return True
    if p.parts[0]=='checks' and p.suffix in {'.json','.txt','.csv'}: return True
    if p.parts[0]=='pilot-processed' and p.name=='pilot-cpa.csv': return True
    return False

def _check_terminal(run,work):
    if run.is_symlink() or run.parent.resolve()!= (work/'runs').resolve(): raise ValueError('run escaped owned runs directory')
    result=json.loads((run/'result.json').read_text())
    if result.get('run_id')!=run.name or result.get('status') not in EXIT: raise ValueError('terminal result identity required')
    return result

def _lock(work):
    lock=(work/'.stage-b.lock').open('a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close(); raise ValueError('an analysis is running; cleanup is refused')
    return lock

def plan(run:Path,work:Path,export:Path|None=None):
    with _lock(work):
        _check_terminal(run,work)
        files=_files(run)
        exports=[]
        if export is not None:
            if json.loads((export/'result.json').read_text()).get('run_id')!=run.name: raise ValueError('export run mismatch')
            exports=_files(export)
        token=secrets.token_hex(24)
        choices={}
        for policy in ('all','evidence','minimal'):
            delete=[r for r in files if not _keep(r['path'],policy)]
            # Export layout contains a subset, with detailed evidence under evidence/.
            export_delete=[r for r in exports if not _keep(r['path'].removeprefix('evidence/'),policy)
                           and r['path']!='manifest.json']
            choices[policy]={'delete_files':delete,'delete_export_files':export_delete,
                             'logical_bytes':sum(r['bytes'] for r in delete+export_delete)}
        payload={'schema_version':1,'run_id':run.name,'run_root':str(run.resolve()),
                 'export_root':str(export.resolve()) if export is not None else None,
                 'plan_id':token,'files':files,'export_files':exports,'choices':choices,
                 'default':'all','decision_required':True,
                 'boundary':'logical file bytes, not guaranteed physical VHDX space reclaimed'}
        atomic_json(work/'cleanup-plans'/(token+'.json'),payload)
        return {k:v for k,v in payload.items() if k not in {'files','export_files'}}

def apply(run:Path,work:Path,token:str,choice:str,approval_quote:str,export:Path|None=None):
    if not re.fullmatch(r'[a-f0-9]{48}',token) or choice not in {'all','evidence','minimal'}: raise ValueError('invalid cleanup choice or plan')
    if not approval_quote or not approval_quote.strip(): raise ValueError('explicit human choice text required')
    with _lock(work):
        _check_terminal(run,work)
        path=work/'cleanup-plans'/(token+'.json')
        payload=json.loads(path.read_text())
        if payload.get('applied'): raise ValueError('cleanup plan already consumed')
        if payload['run_id']!=run.name or payload['run_root']!=str(run.resolve()): raise ValueError('wrong run for cleanup plan')
        if payload['export_root']!=(str(export.resolve()) if export is not None else None): raise ValueError('export changed')
        if _files(run)!=payload['files'] or (export is not None and _files(export)!=payload['export_files']):
            raise ValueError('files changed after planning; generate a new plan')
        selected=payload['choices'][choice]
        previous=json.loads((run/'retention.json').read_text()) if (run/'retention.json').exists() else None
        receipt={'schema_version':1,'run_id':run.name,'plan_id':token,'choice':choice,'previous':previous,
                 'approval_quote':approval_quote,'deleted_files':[],'deleted_export_files':[],
                 'accounting_preserved':True,'status':'applying','physical_space_reclaimed':'not_measured'}
        # Persist intent before deleting, so partial failures remain auditable.
        atomic_json(run/'retention.json',receipt)
        for root,key in ((run,'delete_files'),(export,'delete_export_files')):
            if root is None: continue
            receipt_key='deleted_files' if root==run else 'deleted_export_files'
            for row in selected[key]:
                target=root/row['path']
                if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()): raise ValueError('unsafe cleanup target')
                target.unlink()
                receipt[receipt_key].append(row)
                atomic_json(run/'retention.json',receipt)
        receipt['status']='completed'
        atomic_json(run/'retention.json',receipt)
        if export is not None: atomic_json(export/'retention.json',receipt)
        payload['applied']=True
        atomic_json(path,payload)
        return {'schema_version':1,'status':'completed','run_id':run.name,'choice':choice,
                'deleted_file_count':len(receipt['deleted_files'])+len(receipt['deleted_export_files']),
                'logical_bytes_deleted':selected['logical_bytes'],'accounting_preserved':True}
