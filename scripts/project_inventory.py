"""Reproducible footprint and static internal-call inventory; artifacts are not code."""
import ast
import json
import sys
from pathlib import Path

root=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else Path(__file__).resolve().parents[1]
def category(p):
    s=p.relative_to(root).as_posix()
    if s.startswith('runs/'):return 'run_artifacts'
    if s.startswith('tests/'):return 'tests'
    if s.startswith('src/') and '/resources/' in s:return 'skills_and_resources'
    if s.startswith('src/') and p.suffix=='.py':return 'production_python'
    if s.startswith('docs/') and (p.name.startswith('第') or p.name in {'本次验收.md','最终任务书.md'}):return 'historical_documents'
    if s.startswith('docs/') or p.name in {'README.md','AGENTS.md'}:return 'current_documents'

stats={};modules=[]
for base in ['src','tests','docs','runs','README.md','AGENTS.md']:
    path=root/base
    for p in path.rglob('*') if path.is_dir() else [path]:
        if not p.is_file() or any(x in p.parts for x in ('__pycache__','.execution')) or '.egg-info' in str(p):continue
        group=category(p)
        if not group:continue
        b=p.read_bytes();entry=stats.setdefault(group,dict(files=0,bytes=0,lines=0))
        entry['files']+=1;entry['bytes']+=len(b);entry['lines']+=len(b.splitlines())
        if group=='production_python':
            tree=ast.parse(b);calls=sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)})
            modules.append(dict(path=str(p.relative_to(root)),lines=len(b.splitlines()),calls=calls))
result={'categories':stats,'largest_modules':sorted(modules,key=lambda m:m['lines'],reverse=True)[:12],
        'basis':'Physical bytes and splitlines; run caches excluded; calls are static references, not execution counts'}
Path(sys.argv[1]).write_text(json.dumps(result,indent=2,ensure_ascii=False))
