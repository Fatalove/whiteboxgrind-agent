"""Source-only CI: syntax, catalog and relative documentation links."""
import ast,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[2]
for p in root.rglob('*.py'):
 if '.git' not in p.parts:ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
for p in root.rglob('*.md'):
 if '.git' in p.parts:continue
 for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf8')):
  if ':' in link or link.startswith('#') or '<' in link:continue
  assert (p.parent/link.split('#')[0]).exists(), (str(p),link)
version=(root/'VERSION').read_text().strip()
for p in [root/'plugins/whiteboxgrind/plugin.json',root/'plugins/whiteboxgrind/.codex-plugin/plugin.json']:
 assert json.loads(p.read_text(encoding='utf8'))['version']==version
catalog=json.loads((root/'.agents/plugins/marketplace.json').read_text())
for plugin in catalog['plugins']:assert (root/plugin['source']['path']/'plugin.json').exists()
descriptor=json.loads((root/'plugins/whiteboxgrind/scripts/release-source.json').read_text())
assert re.fullmatch('[a-f0-9]{64}',descriptor['bundle']['sha256'])
assert descriptor['bundle']['url'].startswith('https://github.com/')
print('Python syntax, relative links, versions, marketplace and release descriptor passed')
