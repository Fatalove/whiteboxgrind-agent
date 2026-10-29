"""Run the regression suite in a fixed image with fresh actual host disk samples."""
import datetime,json,os,shutil,subprocess,sys,threading
from pathlib import Path
image=sys.argv[1];out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[2];stop=threading.Event();resource=out/'host-resources.json'
def sample():
 while not stop.is_set():
  value={'schema_version':1,'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'work_free_bytes':shutil.disk_usage(out).free,'export_free_bytes':shutil.disk_usage(out).free}
  temporary=resource.with_suffix('.partial');temporary.write_text(json.dumps(value));os.replace(temporary,resource)
  stop.wait(1)
t=threading.Thread(target=sample);t.start()
while not resource.exists():stop.wait(.02)
args=['docker','run','--rm','--init','--network','none','--user','1000:1000','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','4g','--memory-swap','5g',
 '--tmpfs','/tmp:rw,nosuid,size=268435456,mode=1777','--tmpfs','/work:rw,nosuid,exec,size=67108864,uid=1000,gid=1000',
 '--mount',f'type=bind,source={root},target=/repo,readonly','--mount',f'type=bind,source={out},target=/provenance,readonly',
 '--env','PYTHONPATH=/repo/src','--env','TMPDIR=/work','--env','PYTHONDONTWRITEBYTECODE=1','--env','WBG_HOST_RESOURCES=/provenance/host-resources.json',
 '--entrypoint','/opt/wbg-engine/venv/bin/python',image,'-m','unittest','discover','-s','/repo/tests','-p','test_*.py','-v']
try:
 result=subprocess.run(args,capture_output=True,text=True,timeout=600)
 (out/'tests.log').write_text(result.stdout+result.stderr,encoding='utf8');print(result.stdout+result.stderr)
 (out/'caller.json').write_text(json.dumps({'exit_code':result.returncode,'image':image,'scope':'Synthetic regression in released image, not a new challenge recovery'}))
finally:stop.set();t.join()
raise SystemExit(result.returncode)
