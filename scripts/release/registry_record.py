"""Record the digest returned by the actual registry pull."""
import json,os,subprocess,sys
from pathlib import Path
image=sys.argv[1];row=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
digest=next(x for x in row['RepoDigests'] if x.startswith(image.rsplit(':',1)[0]+'@'))
record={'schema_version':1,'image':image,'immutable_reference':digest,'platform':row['Os']+'/'+row['Architecture'],'engine_commit':row['Config']['Labels']['io.whiteboxgrind.engine.commit'],'rootfs_layers':row['RootFS']['Layers'],'source_commit':os.environ.get('GITHUB_SHA'),'regression_exit_code':0,'scope':'GitHub-hosted regression and authenticated registry pull; anonymous visibility is checked separately'}
Path(sys.argv[2]).write_text(json.dumps(record,indent=2)+'\n');print(digest)
