"""Copy upstream notices from the exact archives without extracting arbitrary paths."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def collect(vendor, destination):
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for archive in sorted(vendor.glob('*.tar.gz')):
        component = archive.name.removesuffix('.tar.gz')
        folder = destination / component
        folder.mkdir()
        notices = []
        with tarfile.open(archive) as handle:
            for member in handle.getmembers():
                base = PurePosixPath(member.name).name
                lower = base.lower()
                if not member.isfile() or not (lower.startswith(('license', 'copying', 'copyright', 'unlicense'))):
                    continue
                content = handle.extractfile(member).read()
                # Content-addressed filenames avoid untrusted archive paths and collisions.
                digest = hashlib.sha256(content).hexdigest()
                name = digest[:12] + '-' + base
                (folder / name).write_bytes(content)
                notices.append({'archive_member': member.name, 'copied_notice': str((folder / name).relative_to(destination)), 'sha256': digest})
            if component.startswith('asynchronous-'):
                member = next(item for item in handle.getmembers() if item.isfile() and PurePosixPath(item.name).name == 'README.md')
                content = handle.extractfile(member).read()
                (folder / 'upstream-README.md').write_bytes(content)
                notices.append({'archive_member': member.name, 'copied_notice': str((folder / 'upstream-README.md').relative_to(destination)),
                                'sha256': hashlib.sha256(content).hexdigest(),
                                'note': 'Upstream README identifies Boost Software License 1.0 and its official license URL; inline header notices retained in source archive'})
        records.append({'source_archive': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'notices': notices})
    result = {'schema_version': 1, 'scope': 'Actual upstream archive notices; source archives accompany this inventory. This inventory is not a public-release approval.',
              'components': records, 'additional_runtime_notices': ['/usr/share/doc', '/usr/share/common-licenses', '/opt/wbg-engine/venv/lib/python3.10/site-packages'],
              'powershell_notices': 'LICENSE.txt and ThirdPartyNotices.txt in the unchanged official ZIP',
              'project_license_selection': 'pending_before_public_release'}
    (destination / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return {'components': len(records), 'notices': sum(len(row['notices']) for row in records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.vendor, args.destination)))
