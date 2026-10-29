"""Select the exact platform layers loaded from the verified release archive."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2];lock=json.loads((root/'container/release-image.json').read_text())
ids=subprocess.check_output(['docker','image','ls','--no-trunc','--quiet','--filter','label=io.whiteboxgrind.engine.commit='+lock['engine_commit']],text=True).split()
matches=[]
for id in set(ids):
 row=json.loads(subprocess.check_output(['docker','image','inspect',id],text=True))[0]
 if row['RootFS']['Layers']==lock['rootfs_layers'] and row['Config']['Labels']['org.opencontainers.image.version']==lock['version'] and row['Architecture']=='amd64' and row['Os']=='linux':matches.append(row['Id'])
assert len(matches)==1,'Release platform layers did not select exactly one image'
print('LOCAL_IMAGE='+matches[0])
