"""Count physical project content separately from retained execution archives."""
import argparse,json,subprocess
from pathlib import Path


def category(path):
    if path.startswith('src/consensus_assurance/') and path.endswith('.py'):return 'production_python'
    if path.startswith('tests/') and path.endswith('.py'):return 'test_python'
    if path.startswith('src/consensus_assurance/resources/'):return 'runtime_resources'
    if path.startswith('docs/') or path in {'README.md','AGENTS.md'}:return 'documentation'
    if path.startswith('runs/'):return 'retained_run_artifacts'


def count(data):return {'files':1,'bytes':len(data),'lines':len(data.splitlines())}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();before={};after={}
    def add(target,key,data):
        row=target.setdefault(key,{'files':0,'bytes':0,'lines':0})
        for k,v in count(data).items():row[k]+=v
    paths=subprocess.check_output(['git','ls-tree','-rz','--name-only','HEAD','src','tests','docs','runs','README.md','AGENTS.md']).decode().split('\0')
    for name in filter(None,paths):
        key=category(name)
        if not key:continue
        # The retained archive is explicitly checked unchanged by git diff in this audit.
        data=Path(name).read_bytes() if key=='retained_run_artifacts' else subprocess.check_output(['git','show','HEAD:'+name])
        add(before,key,data)
    current=[p for root in ['src','tests','docs'] for p in Path(root).rglob('*') if p.is_file()]+[Path('README.md'),Path('AGENTS.md')]
    for path in current:
        if '__pycache__' in path.parts or '.egg-info' in str(path):continue
        key=category(str(path))
        if key:add(after,key,path.read_bytes())
    after['retained_run_artifacts']=before['retained_run_artifacts']
    result={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'before':before,'after':after,
        'largest_modules':sorted([{'path':str(p),**count(p.read_bytes())} for p in Path('src/consensus_assurance').rglob('*.py')],key=lambda r:r['lines'],reverse=True)[:10],
        'basis':'Physical lines including blank lines/comments. Only the tracked retained archive is counted; generated regression outputs and third-party environments are excluded. No remaining historical round documents at the initial HEAD.'}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
