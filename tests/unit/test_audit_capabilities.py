"""Stable R1-R5/R8 capabilities; R6/R7 retain actual execution and TLC suites."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from consensus_assurance.core.types import ConsensusAuditSpec,Activity,Behavior,Fact,Surface,TargetProfile,AuditQuestion
from consensus_assurance.workflow.audit_spec import validate,accept,SpecIssue,load


@pytest.mark.parametrize('applicability',['unknown','externalized','not_applicable','applicable'])
def test_R1_incomplete_coherent_inventory_and_aggregated_errors(prepared,applicability):
    _,state,_,_=prepared;spec=inventory(state.materials[0].id,applicability)
    spec.activities[2].applicability=applicability
    raw=spec.model_dump(mode='json');second=dict(raw['facts'][0],id='second')
    raw['facts'].append(second)
    raw['behaviors'][0]['produces_fact_ids'].append('second')
    raw['behaviors'][1]['produces_fact_ids']=['fact','second']
    raw['behaviors'][1]['consumes_fact_ids'].append('second')
    for fact in raw['facts']:
        fact.pop('established_by');fact.pop('consumed_by')
    spec=ConsensusAuditSpec.model_validate(raw);validate(state,spec)
    assert all(f.established_by==['producer','consumer'] for f in spec.facts)
    spec.behaviors[0].produces_fact_ids=['missing'];spec.surfaces[0].behavior_ids=['absent']
    with pytest.raises(SpecIssue) as exc:validate(state,spec)
    assert len(exc.value.diagnostics)>=2 and all(d.material_ids for d in exc.value.diagnostics)


@pytest.mark.parametrize('gap',['commit establishment','snapshot selection and transfer'])
def test_R3_unread_intermediate_establishment_has_no_invented_edge(prepared,gap):
    _,state,_,_=prepared;raw=inventory(state.materials[0].id).model_dump(mode='json')
    raw['behaviors'][1]['consumes_fact_ids']=[]
    raw['facts'][0].pop('consumed_by');raw['facts'][0]['unknowns']=[gap+' is unread']
    spec=ConsensusAuditSpec.model_validate(raw);validate(state,spec)
    assert spec.facts[0].consumed_by==[] and spec.behaviors[1].consumes_fact_ids==[]


@pytest.mark.parametrize('variant',['paxos','n2paxos','swift'])
def test_variant_visibility_is_a_subset_of_safe_build_files(tmp_path,variant):
    from consensus_assurance.cli import load_config,main
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.native import source_materials, SourceRange
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


def inventory(source,variant='local'):
    return ConsensusAuditSpec(target_profile=TargetProfile(system_boundary='Controlled '+variant,source_ids=[source]),
        activities=[Activity(class_id='A'+str(n),applicability='unknown',purpose='Coordinate '+str(n),realization_summary='Boundary remains incomplete',source_ids=[source],unknowns=['Unrecovered owner']) for n in range(1,8)],
        behaviors=[Behavior(id='producer',primary_activity='A1',execution_owner='producer loop',protocol_context='one operation',trigger='receive',produces_fact_ids=['fact'],source_ids=[source]),
            Behavior(id='consumer',primary_activity='A5',execution_owner='application loop',protocol_context='one operation',trigger='consume',consumes_fact_ids=['fact'],source_ids=[source])],
        facts=[Fact(id='fact',meaning='The scoped input has been established',identity={'operation':'request'},validity_context='one operation',representation=['queue item'],durability='Not yet established',recovery='Unread',source_ids=[source],unknowns=['Durability unverified'])],
        surfaces=[Surface(entry_point='entry',disposition='mapped',behavior_ids=['producer'],reason='Actual controlled entry',source_ids=[source])])
