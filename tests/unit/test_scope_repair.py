from consensus_assurance.workflow.history import import_record
"""Reproduce archived failures through current project types, without external calls."""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import ReviewReply, GraphPatch
from consensus_assurance.workflow.reviews import validate_resolutions
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update
from consensus_assurance.workflow.output_repair import diagnostic_targets
from test_graph_mutations import controller





def test_cached_plans_leave_new_source_quota(tmp_path,prepared):
    repo,s,_,_=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source')
    e.config.budget.targeted_reads=2;s.usage['targeted_reads']=2
    q=[dict(file='limits.py',start_line=1,end_line=2,reason='Reattach actual cached source')]
    for i in range(4):assert e.read(q,plan_id='cache-'+str(i))['status']=='complete'
    assert s.usage['targeted_reads']==2




import copy,json
import pytest
from consensus_assurance.core.proposals import GraphPatch
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update,apply_scope_update
from consensus_assurance.workflow.repair_policy import split_draft_bindings
from consensus_assurance.workflow.output_repair import OutputRepair,diagnostic_targets


@pytest.mark.parametrize('case',['valid','lost_source','accepted','/bindings/999','/missing/bindings/0','/bindings/-1'])
def test_source_preserving_binding_split(case):
    from consensus_assurance.core.types import Material
    from consensus_assurance.core.proposals import BindingDraft
    from consensus_assurance.core.diagnostics import Diagnostic
    material=Material(id='source',file='local.py',start_line=1,end_line=5,kind='code_observation',content_digest='synthetic',text='def first():\n    return 1\n\ndef second():\n    return 2')
    original=BindingDraft(id='whole',claim_id='o',material_id='source',symbol='first',start_line=1,end_line=5,description='Two related entry points',pending=['Consumer guarantee unknown'])
    parts=[original.model_copy(update={'id':symbol,'symbol':symbol,'start_line':a,'end_line':b}) for symbol,a,b in [('first',1,2),('second',4,5)]]
    patch=OutputRepair(binding_splits=[{'path':case if case.startswith('/') else '/bindings/0','bindings':parts,'rationale':'Keep both actual declarations'}],rationale='Representation only')
    if case=='lost_source':patch.binding_splits[0].bindings[0].end_line=1
    raw={'bindings':[original.model_dump(mode='json')],'units':[{'binding_ids':['whole']}]}
    diagnostics=[Diagnostic(code='declaration_identity',category='location',object_ids=['whole'],message='Multiple declarations',allowed=['representation'])]
    context={'materials':[material.model_dump(mode='json')]}
    if case!='valid':
        with pytest.raises(ValueError):split_draft_bindings(raw,patch,diagnostics,context,{'whole'} if case=='accepted' else set())
    else:
        result=split_draft_bindings(raw,patch,diagnostics,context,set())
        assert result['units'][0]['binding_ids']==['first','second']
        assert all(b['pending']==original.pending and b['associations']==raw['bindings'][0]['associations'] for b in result['bindings'])


def test_explicit_draft_plan_returns_to_real_scope_validation(tmp_path,prepared):
    import shutil
    from test_graph_mutations import controller
    from consensus_assurance.core.proposals import UnitDraft,BindingDraft
    from consensus_assurance.adapters.agents.backend import MockAgent
    repo,s,_,responses=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source')
    u=s.units[0];s.active_unit_id=u.id
    b=BindingDraft.model_validate(responses[1]['bindings'][0]);b.id='additional_view';actual=b.symbol;b.symbol='unknown_declaration'
    draft=UnitDraft(**{k:v for k,v in u.model_dump().items() if k in UnitDraft.model_fields});draft.binding_ids.append(b.id)
    p=GraphPatch(bindings=[b],units=[draft],expected_versions={u.id:u.version},rationale='Add a sourced view without changing the audited responsibility')
    fixed=p.model_copy(deep=True);fixed.bindings[0].symbol=actual
    fixture=tmp_path/'explicit-plan.json';fixture.write_text(json.dumps([p.model_dump(mode='json'),{'draft_patch':fixed.model_dump(mode='json'),'rationale':'The actual declaration resolves the unaccepted identity; keep every behavior line and selected claim'}]))
    e.agent=MockAgent(fixture)
    result,_=e.ask('graph_patch',GraphPatch,{'materials':[m.model_dump(mode='json') for m in s.materials]},lambda candidate:validate_scope_update(s,from_patch(s,u,candidate)))
    assert result.bindings[0].symbol==actual and s.usage['agent_calls']==2
    session=next(iter(s.repair_sessions.values()));assert session['draft_scope_plans'] and session['status']=='accepted'
    assert s.units[0].version==1
    new=apply_scope_update(s,from_patch(s,u,result))
    assert new.version==2 and new.obligation_ids==u.obligation_ids


def test_draft_plan_cannot_smuggle_a_weaker_claim():
    from consensus_assurance.workflow.repair_policy import validate_draft_plan
    before={'claims':[{'id':'o','description':'A strong promise'}],'bindings':[],'units':[]}
    with pytest.raises(ValueError):validate_draft_plan(before,{**before,'claims':[{'id':'o','description':'TRUE'}]})
