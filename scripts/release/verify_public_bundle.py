"""Verify the release descriptor and every immutable ZIP member; extract only the image."""
import hashlib,json,sys,zipfile
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]);archives=list(folder.glob('*.zip'))
assert len(archives)==1,'Expected one release ZIP'
archive=archives[0];descriptor=json.loads((root/'plugins/whiteboxgrind/scripts/release-source.json').read_text())
def digest(stream):
 h=hashlib.sha256()
 while b:=stream.read(2**20):h.update(b)
 return h.hexdigest()
with archive.open('rb') as f:assert digest(f)==descriptor['bundle']['sha256'],'Release ZIP digest differs'
with zipfile.ZipFile(archive) as z:
 manifest=json.loads(z.read('release-manifest.json'))
 assert manifest['version']==(root/'VERSION').read_text().strip()
 names={x['path'] for x in manifest['files']}|{'release-manifest.json'}
 assert set(z.namelist())==names and len(z.namelist())==len(names),'ZIP allowlist differs'
 for row in manifest['files']:
  p=PurePosixPath(row['path']);assert not p.is_absolute() and '..' not in p.parts
  with z.open(row['path']) as f:assert digest(f)==row['sha256'],row['path']
 with z.open(manifest['image']['archive']) as src,(folder/'image.tar').open('wb') as dst:
  while b:=src.read(2**20):dst.write(b)
print(f'Verified {len(names)} ZIP members and extracted fixed image')
