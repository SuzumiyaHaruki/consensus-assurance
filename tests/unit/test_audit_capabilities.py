from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from consensus_assurance.core.submissions import SourceRange

def test_variant_visibility_is_a_subset_of_safe_build_files(tmp_path):
    from consensus_assurance.cli import load_config,main
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.audit import source_materials
    variant='epaxos'
    repo=tmp_path/'source';repo.mkdir()
    families=['paxos','n2paxos','swift','epaxos','fastpaxos','curp']
    for family in families+['replica']:
        (repo/family).mkdir();(repo/family/'node.go').write_text('package '+family+'\n')
    (repo/'go.mod').write_text('module github.com/imdea-software/swiftpaxos\n')
    (repo/'README.md').write_text('Repository orientation')
    (repo/variant/'secret.txt').write_text('Private file')
    (repo/variant/'binary').write_bytes(b'\0')
    cfg=Path(__file__).resolve().parents[2]/f'configs/targets/swiftpaxos_{variant}.yaml'
    config=load_config(str(cfg));snapshot=capture(repo,analysis_roots=config.target.analysis_roots)
    assert all(f'{f}/node.go' in snapshot.files for f in families)
    assert {f'{variant}/node.go','replica/node.go','go.mod','README.md'}==set(snapshot.readable_files)
    for f in families:
        if f!=variant:
            with pytest.raises(ValueError):source_materials(SimpleNamespace(root=repo.parent,state=SimpleNamespace(snapshot=snapshot,materials=[])),[SourceRange(id='hidden',file=f'{f}/node.go',start_line=1,end_line=1,kind='code_observation')])
    assert main(['inspect','--config',str(cfg),'--repo',str(repo),'--runs-dir',str(tmp_path/'inspect')])==0
    saved=json.loads(next((tmp_path/'inspect').glob('*/snapshot.json')).read_text())
    assert saved['files']==snapshot.files and saved['readable_files']==snapshot.readable_files
