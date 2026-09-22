"""Previously unread provider -> existing unit scope -> actual model and TLC/calibration."""
import copy,json,sys
from pathlib import Path
import pytest
from test_verification_workflow import deferred_fixture
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import UnitDraft
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.agents.backend import MockAgent
from consensus_assurance.adapters.storage.files import write_json,Store
from consensus_assurance.core.types import Origin


class ScopeAgent(MockAgent):
    def __init__(self,responses):super().__init__();self.data=responses;self.refine=False
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        if response_type.__name__=='Discovery':
            from regression_support import inventory_response
            return inventory_response(runner,prompt,directory,snapshot_id,timeout)
        p=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]);name=response_type.__name__
        if name=='ReadingPlan':response=self.data[0]
        elif name=='Derivation':
            response=copy.deepcopy(self.data[1])
            if self.refine:response['units'][0]['audit_question']={'question':'Does the consumer stay within its supplied bound?','importance':'The consumer relies on the provider boundary','source_ids':response['claims'][0]['grounding']['expectation_ids'],'event_paths':['Input reaches the consumer'],'trigger_rationale':'One input consumption exercises the responsibility'}
        elif name=='BuildReply':
            if not any(b['id']=='input_binding' for b in p['bindings']):
                assert not any(m['file']=='upstream_support.py' for m in p['materials'])
                response={'bundle':None,'gap':'The actual input producer is unread; read and connect it before generating behavior','requests':self.data[3]['requests'],'reading_purpose':'dependency'}
            else:
                assert p['unit']['previous_id'] and 'input_binding' in p['unit']['binding_ids']
                assert p['unit']['obligation_ids']==['step_obligation']
                from regression_support import fixture_reachability
                response={'bundle':fixture_reachability(self.data[5]),'gap':''}
                for constraint in response['bundle']['constraints']:
                    selected=[b for b in p['bindings'] if b['id'] in constraint.get('binding_ids',[])]
                    if selected:
                        constraint['source_ids']=list(dict.fromkeys(m['id'] for b in selected for m in p['materials'] if m['file']==b['file'] and m['start_line']<=b['end_line'] and m['end_line']>=b['start_line']))
        elif name=='GraphPatch':
            assert any(m['file']=='upstream_support.py' for m in p['new_materials'])
            old=p['units'][0];unit={k:v for k,v in old.items() if k in UnitDraft.model_fields}
            unit=copy.deepcopy(unit);unit['binding_ids'].append('input_binding')
            if self.refine:unit['audit_question']['event_paths'].append('Actual input normalization precedes consumption')
            unit['relation_ids'].append('new_support_path')
            edge=copy.deepcopy(self.data[1]['relations'][0]);edge.update(id='new_support_path',source='input_obligation',target='input_binding',kind='boundary',group=None,rationale='Actual provider supplies the input',pending=['Not a proof of its guarantee'])
            response={**copy.deepcopy(self.data[4]),'relations':[edge], 'units':[unit],'expected_versions':{old['id']:old['version']}}
        elif name=='ScopeAssessment':
            update=p['scope_update']
            response={'decision':'refinement','source_ids':update['source_ids'],'addressed_fields':p['required_fields'],'preserved_question':update['original_question'],'rationale':'The actual provider source refines the input production event; the checked question and fault assumptions remain unchanged','remaining_unknowns':['The provider is not separately proven']}
        elif name in {'ReviewReply','ReviewKnowledgeReply'}:
            items=[]
            for c in p['review_contract']:
                for aspect in c['required_aspects']:
                    items.append({'target_id':c['target_id'],'aspect':aspect,'status':'no_issue_found','source_ids':c['required_material_ids'],'rationale':'The supplied actual synthetic sources support the scoped question' + "\n" + 'A different legal provider can meet the same responsibility' + "\n" + 'A violated provider boundary can change the reachable counter behavior','limitations':(['Finite synthetic instance; no production consensus claim']) + ([])})
            response={'items':items,'limitations':[]}
        elif name=='SpecRefinement':response={'understanding':'The current synthetic source set has a separate unverified input responsibility','delta':{'rationale':'Retain current descriptive unknowns'},'limitations':['The separate input obligation is not automatically discharged']}
        else:raise AssertionError(name)
        if name=='Derivation':
            from regression_support import bounded_derivation
            response=bounded_derivation(response,p)
        directory.mkdir(parents=True,exist_ok=True);(directory/'prompt.txt').write_text(prompt);write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
        check=runner.run([sys.executable,'-c','print("Explicit scope-reconnection regression responder")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
        return check,response_type.model_validate(response)


def setup(tmp_path,prepared,tlc):
    repo,fixture=deferred_fixture(tmp_path,prepared[3]);responses=json.loads(fixture.read_text())
    cfg=Config(execution_backend='python',agent_backend='mock',tlc_jar=str(tlc[0].jar),allow_experiments=True)
    cfg.budget.agent_calls=20;cfg.budget.semantic_reviews=6;cfg.budget.exploration_rounds=3;cfg.budget.material_chars=5000
    impl,_,verifier,knowledge=assemble(cfg)
    return repo,cfg,(impl,ScopeAgent(responses),verifier,knowledge,''),tmp_path/'scope-run'


@pytest.mark.real
def test_actual_new_read_reconnects_existing_unit_before_model(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc);state=Engine(cfg,root,*args).start(repo)
    assert state.models,state.stop_reason
    assert len([u for u in state.units if u.previous_id])==1
    assert len([r for r in state.revisions if r.kind=='F3'])==1
    assert state.models[0].unit_id==state.units[0].id and state.models[0].binding_ids==['step_binding','input_binding']
    assert state.units[0].obligation_ids==['step_obligation']
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks),state.stop_reason
    assert any(c.status=='compatible' for c in state.calibrations),state.stop_reason
    assert not any(t.trigger.startswith('after_local:') for t in state.inquiry_tasks)
    assert state.units[0].status=='checked',state.stop_reason
    assert state.usage['agent_calls']<=20
    assert any('input_binding' in basis.get('dependency_versions',{}) for r in state.semantic_reviews for basis in r.context_dependencies.values())
    assert all(m.snapshot_id==state.snapshot.id for m in state.models)


@pytest.mark.real
def test_event_refinement_executes_explicit_assessment_before_build(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc);args[1].refine=True
    state=Engine(cfg,root,*args).start(repo)
    assert state.models,state.stop_reason
    assert any(c.parameters.get('agent_task')=='scope_review' for c in state.checks)
    proposal=next(v['proposal'] for v in state.scope_updates.values() if v['status']=='accepted')
    assert proposal['assessment']['preserved_question']==proposal['original_question']
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks)


@pytest.mark.real
def test_saved_scope_assessment_reused_at_exact_semantic_budget(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc);args[1].refine=True;cfg.budget.semantic_reviews=2
    class Interrupted(Engine):
        def checkpoint(self,name):
            super().checkpoint(name)
            if name=='action_result_saved' and self.state.pending_action.kind=='agent:scope_review':raise RuntimeError('Scope assessment persisted at final semantic budget slot')
    with pytest.raises(RuntimeError):Interrupted(cfg,root,*args).start(repo)
    state=Engine(cfg,root,*args).resume()
    assert state.models,state.stop_reason
    assert state.usage['semantic_reviews']==2
    assert len([c for c in state.checks if c.parameters.get('agent_task')=='scope_review'])==1
