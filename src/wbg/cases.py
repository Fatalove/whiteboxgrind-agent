"""Prepare portable single-target tasks without changing user input."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import secrets

from . import config
from .protocol import atomic_json


def _abi(data: bytes) -> str:
    if data.startswith(b'\x7fELF'):
        raise config.UnsupportedConfig('input_format_elf', '需要兼容的 AES-128 C 源码，当前不接受 ELF')
    text = data.decode('latin1')
    # Remove comments and quoted literals before recognizing a function definition.
    text = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', ' ', text, flags=re.S)
    signature = re.search(r'\bvoid\s+AES_128_encrypt\s*\(([^()]*)\)\s*\{', text)
    if not signature:
        raise config.UnsupportedConfig('target_interface', '需要 AES_128_encrypt(out, in) 的双字节指针函数定义；不自动改写题目')
    params = signature[1].split(',')
    types=[]
    for param in params:
        item=re.fullmatch(r'\s*(unsigned\s+)?char\s*\*\s*[A-Za-z_]\w*\s*', param)
        if not item:
            raise config.UnsupportedConfig('target_interface', '首发仅支持两个同类型 char* 或 unsigned char* 参数')
        types.append('unsigned-char-pointer' if item[1] else 'char-pointer')
    if len(types)!=2 or types[0]!=types[1]:
        raise config.UnsupportedConfig('target_interface', '首发需要两个同类型字节指针参数，顺序为 out、in')
    return types[0]


def prepare(root: Path, source: str | None = None, *, example=False, seed=None, trace_count=None) -> dict:
    if root.is_symlink():
        raise ValueError('task root must not be a symlink')
    root=root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    inputs=root/'input'
    if inputs.is_symlink():
        raise ValueError('input directory must not be a symlink')
    inputs.mkdir(exist_ok=True)
    if example:
        if source:
            raise ValueError('choose --example or --source')
        example_file=inputs/'ordinary-aes128.c'
        fixture=(config.PROJECT/'fixtures/ordinary-aes128/adapter.c').read_bytes()
        if example_file.exists() and example_file.read_bytes()!=fixture:
            raise ValueError('existing input differs; choose a new task directory')
        if not example_file.exists():
            example_file.write_bytes(fixture)
    files=sorted(p for p in inputs.rglob('*') if p.is_file() and p.suffix.lower()=='.c')
    if not files:
        for item in inputs.rglob('*'):
            if item.is_file() and not item.is_symlink():
                with item.open('rb') as stream:
                    if stream.read(4)==b'\x7fELF':
                        raise config.UnsupportedConfig('input_format_elf','当前仅支持兼容 AES-128 C 源码，不能直接分析 ELF')
    if source:
        selected=(inputs/source).resolve(strict=True)
        if not selected.is_relative_to(inputs.resolve()) or selected not in [p.resolve() for p in files]:
            raise ValueError('--source must select a C file inside input')
    elif len(files)!=1:
        return {'schema_version':1,'status':'needs_input' if not files else 'needs_selection',
                'case_root':str(root),'candidates':[p.relative_to(inputs).as_posix() for p in files],
                'detail':'把兼容 C 源码放入 input；多个文件时通过 --source 指定主文件','analysis_started':False}
    else:
        if files[0].is_symlink():
            raise ValueError('symlink inputs are not supported')
        selected=files[0].resolve(strict=True)
    if not selected.is_relative_to(inputs.resolve()):
        raise ValueError('source escaped input directory')
    if any(p.is_symlink() for p in [selected, *selected.parents] if p.is_relative_to(root)):
        raise ValueError('symlink inputs are not supported')
    payload=selected.read_bytes()
    digest=hashlib.sha256(payload).hexdigest()
    teaching=payload==(config.PROJECT/'fixtures/ordinary-aes128/adapter.c').read_bytes()
    abi='unsigned-char-pointer' if teaching else _abi(payload)
    destination=root/'task.json'
    if destination.exists():
        raw,effective=config.load(destination)
        if effective['target']['sha256']!=digest or Path(effective['target']['source'])!=selected:
            raise ValueError('task identity changed; preserve this task and create a new task directory')
        if seed is not None and seed!=raw['inputs']['seed'] or trace_count is not None and trace_count!=raw['inputs']['trace_count']:
            raise ValueError('existing task parameters are retained; no silent budget-group reset')
    else:
        count=trace_count if trace_count is not None else (100 if teaching else 500)
        raw={'schema_version':2,'experiment':'case-'+digest[:24],
             'environment':{'backend':'docker','distribution':'Ubuntu-22.04'},
             'target':{'adapter':'aes128-c','abi':abi,'source':selected.relative_to(root).as_posix(),
                       'sha256':digest,'compile_flags':config.COMPILE_FLAGS.copy()},
             'inputs':{'generator':'sha256-counter-v1','seed':int(digest[:16],16) if seed is None else seed,
                       'pilot_count':'auto','trace_count':count,'holdout_count':16},
             'analysis':copy.deepcopy(config.ANALYSIS_DEFAULTS),'resources':copy.deepcopy(config.RESOURCE_DEFAULTS)}
        if teaching:
            raw['target']['fixture']='ordinary-aes128'
        config.normalize(raw,root)
        atomic_json(destination,raw)
    if (root/'output').is_symlink():
        raise ValueError('output directory must not be a symlink')
    (root/'output').mkdir(exist_ok=True)
    return {'schema_version':1,'status':'prepared','case_root':str(root),'config':str(destination),
            'target_sha256':digest,'abi':abi,'seed':raw['inputs']['seed'],
            'next_output':str(root/'output'/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4))),
            'analysis_started':False,'boundary':'仅检查接口和配置；实际兼容性由构建、I/O、pilot 和独立验证判定'}
