"""Synthetic grants for regression; no private contest source or human quote."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from wbg import budgets, config

def configure(test):
    temporary=tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    root=Path(temporary.name)
    raw,_=config.demo()
    raw['experiment']='synthetic-budget-case'
    raw['inputs']['trace_count']=500
    raw['inputs']['seed']=20261023
    raw['resources']['timeout_seconds']=None
    raw['target']['source']=str(config.PROJECT/'fixtures/ordinary-aes128/adapter.c')
    test.test_config=root/'task.json'
    test.test_config.write_text(json.dumps(raw),encoding='utf8')
    grant={'target_sha256':raw['target']['sha256'],'approved_by':'user','approval_quote':'SYNTHETIC TEST CHOICE ONLY',
           'max_total_seconds':7200,'max_total_output_bytes':5120*2**20}
    auth=root/'authorizations.json'
    auth.write_text(json.dumps({'schema_version':1,'groups':{'synthetic-budget-case:20261023':grant}}),encoding='utf8')
    interactive=root/'interactive.json'
    interactive.write_text(json.dumps({'schema_version':1,'groups':{'synthetic-budget-case:20261023':
        dict(grant,max_total_seconds=None,time_policy='user_controlled')}}),encoding='utf8')
    for attribute,value in [('AUTHORIZATIONS',auth),('INTERACTIVE_AUTHORIZATIONS',interactive)]:
        patcher=patch.object(budgets,attribute,value)
        patcher.start();test.addCleanup(patcher.stop)
