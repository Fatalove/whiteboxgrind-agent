"""Read-only resource observations; virtual filesystem capacity is not host free space."""
import base64
import json
import os
from pathlib import Path
import shutil
from .runtime import BACKEND, WORK_ROOT, container_limits, host_resources


def memory_info():
    result = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines()
              if line.split(':', 1)[0] in {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}}
    if BACKEND == 'docker':
        try:
            available = container_limits()['memory_available_bytes']
            result['EffectiveMemAvailable'] = min(result['MemAvailable'], available) if available is not None else None
        except (OSError, ValueError, ZeroDivisionError):
            result['EffectiveMemAvailable'] = None
    return result


def advice(host=None):
    if host is None and os.environ.get('WBG_WINDOWS_HOST_B64'):
        host = json.loads(base64.b64decode(os.environ['WBG_WINDOWS_HOST_B64']).decode('utf-8')).get('resources')
    host = host or {}
    mem = memory_info()
    limits = None
    if BACKEND == 'docker':
        try:
            limits = container_limits()
            available = (min(mem['MemAvailable'], limits['memory_available_bytes'])
                         if limits['memory_available_bytes'] is not None else None)
        except (OSError, ValueError, ZeroDivisionError) as exc:
            limits = {'error': repr(exc)}
            available = None
    else:
        available = mem['MemAvailable']
    host_available = host.get('memory_available_bytes')
    drive = host.get('wsl_storage_drive')
    export_drive = host.get('export_drive')
    volumes = host.get('volumes', {})
    physical = volumes.get(drive, {}).get('free_bytes') if drive else None
    if BACKEND == 'docker':
        try:
            measured = host_resources()
            drive = measured['work_drive'].rstrip(':\\/')
            export_drive = measured['export_drive'].rstrip(':\\/')
            physical = min(measured['work_free_bytes'], measured['export_free_bytes'])
        except (OSError, ValueError, KeyError, TypeError):
            drive = export_drive = physical = None
    reserve = 20 * 2**30
    return {'host': host, 'linux_memory_bytes': mem,
            'work_volume_virtual_free_bytes': shutil.disk_usage(WORK_ROOT).free,
            'container_limits': limits,
            'physical_work_drive': drive, 'physical_export_drive': export_drive,
            'shared_physical_volume': bool(drive and drive == export_drive),
            'suggested_memory_bytes': min(int(host_available * 0.6), max(0, available - 512 * 2**20))
                                      if host_available is not None and available is not None else None,
            'suggested_additional_output_bytes': int(max(0, physical - reserve) * 0.6) if physical is not None else None,
            'physical_volume_reserve_bytes': reserve,
            'scope': '60% planning advice, no preallocation; host mapping absent means unknown, not virtual capacity'}
