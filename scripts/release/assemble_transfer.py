"""Reassemble a byte-exact release after slow-client multipart transport."""
import hashlib,json,sys
from pathlib import Path
folder=Path(sys.argv[1]);root=Path(__file__).resolve().parents[2]
manifest=json.loads((folder/'transfer-parts.json').read_text())
descriptor=json.loads((root/'plugins/whiteboxgrind/scripts/release-source.json').read_text())
expected=descriptor['bundle']['sha256'];assert manifest['sha256']==expected
target=folder/('whiteboxgrind-'+(root/'VERSION').read_text().strip()+'-windows.zip');whole=hashlib.sha256()
with target.open('wb') as out:
 for row in manifest['parts']:
  assert Path(row['name']).name==row['name'] and row['name'].startswith('transfer-windows.part-')
  h=hashlib.sha256();count=0
  with (folder/row['name']).open('rb') as src:
   while b:=src.read(2**20):out.write(b);whole.update(b);h.update(b);count+=len(b)
  assert count==row['bytes'] and h.hexdigest()==row['sha256']
assert whole.hexdigest()==expected,'Assembled archive differs'
print('Byte-exact assembled release:',whole.hexdigest())
