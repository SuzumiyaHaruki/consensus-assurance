import copy,json
import pytest
from test_round9_failures import archived,reply
from consensus_assurance.core.proposals import GraphPatch
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update,apply_scope_update
from consensus_assurance.workflow.repair_policy import split_draft_bindings
from consensus_assurance.workflow.output_repair import OutputRepair,diagnostic_targets


def split_patch(p):
    groups=[]
    for index,b in enumerate(p.bindings):
        if b.id=='B_commit_Configuration':
            entries=[('ServerID',59,59),('ServerAddress',62,62),('Server',65,72),('Configuration',78,80)]
        elif b.id=='B_commit_ServerSuffrage':entries=[('ServerSuffrage',9,9),('Voter',11,24)]
        else:continue
        parts=[]
        for symbol,a,z in entries:
            item=b.model_dump(mode='json');item.update(id=b.id+'_'+symbol,symbol=symbol,start_line=a,end_line=z)
            item['anchor']={'material_id':b.material_id,'symbol':symbol,'start_line':a if symbol!='Voter' else 15,'end_line':a if symbol!='Voter' else 15,'kind':'declaration'}
            parts.append(item)
        groups.append({'path':'/bindings/'+str(index),'bindings':parts,'rationale':'Split actual adjacent declarations without removing code lines or changing responsibility'})
    return OutputRepair(binding_splits=groups,rationale='Offline representation correction; all original source and semantic associations retained')


def test_archived_multideclaration_draft_can_reconnect_without_changing_question():
    s=archived();p=GraphPatch.model_validate(reply('f6577be6da9a47f68581404d750a55d6-graph_patch'));u=next(u for u in s.units if u.id=='U_commit')
    with pytest.raises(ValueError) as exc:validate_scope_update(s,from_patch(s,u,p))
    ds=exc.value.diagnostics
    assert {d.code for d in ds}=={'declaration_identity'}  # Local input roles need no invented external O.
    patch=split_patch(p)
    context={'materials':[m.model_dump(mode='json') for m in s.materials]}
    # Resolve each split from a fresh candidate: previous insertion must not shift another pointer.
    merged=split_draft_bindings(p.model_dump(mode='json'),patch,ds,context,{b.id for b in s.bindings})
    fixed=GraphPatch.model_validate(merged);update=from_patch(s,u,fixed)
    assert validate_scope_update(s,update)==[]
    new=apply_scope_update(s,update)
    assert new.obligation_ids==u.obligation_ids and new.goal_ids==u.goal_ids and new.audit_question==u.audit_question
    assert len(new.binding_ids)>len(u.binding_ids)
    assert s.models==[]


def test_split_cannot_erase_meaningful_source_or_modify_accepted_binding():
    s=archived();p=GraphPatch.model_validate(reply('f6577be6da9a47f68581404d750a55d6-graph_patch'));u=next(u for u in s.units if u.id=='U_commit')
    with pytest.raises(ValueError) as exc:validate_scope_update(s,from_patch(s,u,p))
    patch=split_patch(p);patch.binding_splits=patch.binding_splits[:1]
    patch.binding_splits[0].bindings=patch.binding_splits[0].bindings[1:]
    with pytest.raises(ValueError):split_draft_bindings(p.model_dump(mode='json'),patch,exc.value.diagnostics,{'materials':[m.model_dump(mode='json') for m in s.materials]},set())


@pytest.mark.parametrize('path',['/bindings/999','/missing/bindings/0','/bindings/-1'])
def test_malformed_split_pointer_is_a_repair_error_not_controller_crash(path):
    s=archived();p=GraphPatch.model_validate(reply('f6577be6da9a47f68581404d750a55d6-graph_patch'));patch=split_patch(p)
    patch.binding_splits=patch.binding_splits[:1];patch.binding_splits[0].path=path
    with pytest.raises(ValueError):split_draft_bindings(p.model_dump(mode='json'),patch,[],{},set())


def test_explicit_draft_plan_returns_to_real_scope_validation(tmp_path,prepared):
    import shutil
    from test_round6_boundaries import controller
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
