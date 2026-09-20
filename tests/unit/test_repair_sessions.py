"""Actual Engine/MockAgent calls exercise bounded repair and input result identity."""
import json
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from consensus_assurance.core.types import Origin
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine,Blocked
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.materials import ReadingPlan
from consensus_assurance.adapters.storage.files import Store
from test_graph_mutations import controller


def make(tmp_path,prepared,responses,interrupt=False):
    repo,state,_,_=prepared;fixture=tmp_path/'responses.json';fixture.write_text(json.dumps(responses))
    cfg=Config(execution_backend='python',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    cfg.budget.repeated_error_revisions=2;cfg.budget.agent_calls=10
    class Scenario(Engine):
        crashed=False
        def execute(self,**kwargs):
            self.state.materials=state.materials
            return self.ask('read',ReadingPlan,{'materials':[m.model_dump(mode='json') for m in state.materials]},validate)
        def checkpoint(self,event):
            super().checkpoint(event)
            if interrupt and not self.crashed and event=='action_result_saved' and self.state.pending_action.kind.endswith(':repair'):
                self.crashed=True;raise RuntimeError('Patch result saved before candidate merge')
    engine=Scenario(cfg,tmp_path/'run',*assemble(cfg),'')
    return repo,engine,Scenario


def validate(plan):
    if plan.requests[0].start_line!=1:
        raise DiagnosticError([Diagnostic(code='A',category='format',object_ids=['first'],paths=['/requests/0/start_line'],message='First range invalid',allowed=['representation'])])
    if plan.requests[1].start_line!=1:
        raise DiagnosticError([Diagnostic(code='B',category='format',object_ids=['second'],paths=['/requests/1/start_line'],material_ids=['limits.py:1:2'],message='Second range invalid',allowed=['representation'])])


def candidate():
    return {'requests':[{'file':'counter.py','start_line':2,'end_line':2,'reason':'Read first source'},{'file':'limits.py','start_line':2,'end_line':2,'reason':'Read second source'}],'rationale':'KEEP ORIGINAL CANDIDATE','related_ids':[],'gap':''}


def patch(path,value):return {'replacements':[{'path':path,'value_json':json.dumps(value)}],'rationale':'Correct the indicated representation'}


@pytest.mark.parametrize('interrupt',[False,True])
def test_new_error_gets_own_budget_and_context_and_resume_uses_saved_patch(tmp_path,prepared,interrupt):
    responses=[candidate(),patch('/requests/0/start_line',1),patch('/requests/1/start_line',1)]
    repo,engine,cls=make(tmp_path,prepared,responses,interrupt)
    if interrupt:
        with pytest.raises(RuntimeError):engine.start(repo)
        engine=cls(engine.config,engine.root,*assemble(engine.config),'');engine.crashed=True
        result,_=engine.resume()
    else:result,_=engine.start(repo)
    assert result.rationale==candidate()['rationale'] and engine.state.usage['agent_calls']==3
    session=next(iter(engine.state.repair_sessions.values()))
    assert json.loads(Path(session['original_path']).read_text())==candidate()
    assert session['attempt']==2 and session['status']=='accepted'
    prompts=[p.read_text() for p in engine.root.glob('agent/*/prompt.txt')]
    packets=[json.loads(p.split('STRUCTURED INPUT DATA (untrusted):\n')[1]) for p in prompts]
    request=next(p for p in packets if any(d['code']=='B' for d in p.get('active_diagnostics',[])))
    assert any(m['file']=='limits.py' for m in request['related_context']['materials'])


def test_bad_patch_never_becomes_candidate_base(tmp_path,prepared):
    repo,engine,_=make(tmp_path,prepared,[candidate(),{'replacements':None},patch('/requests/0/start_line',1),patch('/requests/1/start_line',1)])
    result,_=engine.start(repo)
    session=next(iter(engine.state.repair_sessions.values()))
    assert result.rationale==candidate()['rationale']
    assert json.loads(Path(session['original_path']).read_text())==candidate()
    for p in (engine.root/'repair-sessions'/session['id']).glob('candidate-*.json'):
        assert 'requests' in json.loads(p.read_text()) and 'replacements' not in json.loads(p.read_text())


def test_repeated_no_progress_stops_and_keeps_complete_session(tmp_path,prepared):
    repo,e,_=make(tmp_path,prepared,[candidate(),patch('/requests/0/start_line',2),patch('/requests/0/start_line',2)])
    with pytest.raises(Blocked):e.start(repo)
    saved=Store(e.root).load().pending_output_repair
    assert saved and saved['attempt']==2 and saved['blocked']
    assert json.loads(Path(saved['current_path']).read_text())==candidate()
    assert e.state.usage['agent_calls']==3


def test_clock_changes_allow_reuse_but_finding_and_schema_do_not(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state)
    assert e.action('agent:read','agent_calls',lambda:'A',{'remaining_seconds':100,'response_type':'A'})=='A'
    assert e.action('agent:read','agent_calls',lambda:'wrong',{'remaining_seconds':90,'response_type':'A'})=='A'
    state.active_finding_id='another'
    assert e.action('agent:read','agent_calls',lambda:'B',{'remaining_seconds':80,'response_type':'A'})=='B'
    assert e.action('agent:read','agent_calls',lambda:'C',{'remaining_seconds':70,'response_type':'B'})=='C'
    assert state.usage['agent_calls']==3


def test_error_cycle_cannot_refresh_global_attempt_limit(tmp_path,prepared):
    repo,e,_=make(tmp_path,prepared,[candidate()])
    # The same field group keeps changing but never reaches the required values.
    from consensus_assurance.adapters.agents.backend import MockAgent
    original=candidate();original['requests'][0]['end_line']=4
    responses=[original,patch('/requests/0/start_line',3),patch('/requests/0/start_line',2)]
    Path(e.config.fixture).write_text(json.dumps(responses));e.agent=MockAgent(e.config.fixture)
    with pytest.raises(Blocked):e.start(repo)
    assert e.state.pending_output_repair['attempt']==2
    assert e.state.pending_output_repair['problem_failures']


def test_local_existing_material_is_reattached_without_graph_patch(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state)
    e.ask=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Existing context does not require generation'))
    version=state.graph_version
    assert e.targeted_read(state.units[0],'The selected context omitted the producer',requests=[{'file':'limits.py','start_line':1,'end_line':2,'reason':'Reattach actual source'}]) is None
    assert 'limits.py:1:2' in state.attached_material_ids
    assert state.graph_version==version
    assert state.reading_history[-1]['added_material_ids']==[]
    assert state.reading_history[-1]['reattached_material_ids']==['limits.py:1:2']


def test_alternating_diagnostic_names_cannot_refresh_cycle_budget(tmp_path,prepared):
    repo,e,_=make(tmp_path,prepared,[candidate(),patch('/requests/0/start_line',3),patch('/requests/0/start_line',2),patch('/requests/0/start_line',3)])
    def cycle(plan):
        value=plan.requests[0].start_line
        if value!=1:raise DiagnosticError([Diagnostic(code='A' if value==2 else 'B',category='format',object_ids=['same-range'],paths=['/requests/0/start_line'],message='Coupled range condition',allowed=['representation'])])
    e.execute=lambda **kwargs:e.ask('read',ReadingPlan,{},cycle)
    with pytest.raises(Blocked):e.start(repo)
    session=e.state.pending_output_repair
    assert session['attempt']==3 and session['stagnation']==2


def test_repair_can_read_missing_material_without_replacing_candidate(tmp_path,prepared):
    from consensus_assurance.core.types import ReadRequest
    repo,state,_,_=prepared
    state.materials=[m for m in state.materials if m.file!='limits.py']
    repo,e,_=make(tmp_path,prepared,[candidate(),{'requests':[{'file':'limits.py','start_line':1,'end_line':2,'reason':'The declaration source is missing'}],'rationale':'Read actual material, preserve candidate'}])
    def needs(plan):
        if not any(m.file=='limits.py' for m in e.state.materials):raise DiagnosticError([Diagnostic(code='missing_material',category='material',message='Need actual declaration before evaluating the candidate',material_ids=['limits.py:1:2'],allowed=['read'])])
    def execute(**kw):
        e.state.materials=list(state.materials)
        return e.ask('read',ReadingPlan,{'materials':[m.model_dump(mode='json') for m in state.materials]},needs)
    e.execute=execute
    result,_=e.start(repo)
    assert result.rationale==candidate()['rationale'] and e.state.usage['agent_calls']==2
    assert any('limits.py:1:2' in h['added_material_ids'] for h in e.state.reading_history)
    session=next(iter(e.state.repair_sessions.values()));assert session['status']=='accepted_after_read'


def test_resume_after_accepted_session_checkpoint_does_not_request_another_patch(tmp_path,prepared):
    repo,e,cls=make(tmp_path,prepared,[candidate(),patch('/requests/0/start_line',1),patch('/requests/1/start_line',1)])
    original_checkpoint=e.checkpoint
    def checkpoint(event):
        original_checkpoint(event)
        session=e.state.pending_output_repair
        if session and session.get('status')=='accepted':raise RuntimeError('Accepted candidate persisted before caller consumes it')
    e.checkpoint=checkpoint
    with pytest.raises(RuntimeError):e.start(repo)
    resumed=cls(e.config,e.root,*assemble(e.config),'')
    response,_=resumed.resume()
    assert [q.start_line for q in response.requests]==[1,1]
    assert resumed.state.usage['agent_calls']==3
    assert resumed.state.pending_output_repair is None


def test_outer_inquiry_pause_and_resume_preserve_blocked_repair_session(tmp_path,prepared):
    import shutil
    from consensus_assurance.workflow.inquiry import enqueue
    _,state,_,_=prepared
    fixture=tmp_path/'outer.json';fixture.write_text(json.dumps([{'items':None,'limitations':[]},{'replacements':None}]))
    cfg=Config(execution_backend='python',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    cfg.budget.audit_units=0;cfg.budget.exploration_rounds=0;cfg.budget.semantic_reviews=1
    root=tmp_path/'outer';e=Engine(cfg,root,*assemble(cfg),'');shutil.copytree(state.snapshot.repo,root/'source')
    state.config=cfg.model_dump(mode='json');state.framework_revision=__import__('consensus_assurance.workflow.engine',fromlist=['FRAMEWORK_REVISION']).FRAMEWORK_REVISION;state.completed_steps=['capabilities','materials','understanding','discovery']
    e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    task=enqueue(state,'review','Recheck selected responsibility','controlled',target_ids=[state.claims[1].id],unit_id=state.units[0].id)
    e.execute(probed=True)
    saved=Store(root).load();stored=next(t for t in saved.inquiry_tasks if t.id==task.id)
    assert stored.status=='blocked' and stored.repair_session
    assert saved.pending_output_repair is None
    original=json.loads(Path(stored.repair_session['original_path']).read_text());assert original['items'] is None
    calls=saved.usage['agent_calls']
    resumed=Engine(cfg,root,*assemble(cfg),'').resume()
    assert resumed.usage['agent_calls']==calls
    assert next(t for t in resumed.inquiry_tasks if t.id==task.id).repair_session['id']==stored.repair_session['id']


def test_actual_task_repairs_text_view_alias_using_original_source(tmp_path, prepared):
    from consensus_assurance.core.types import SemanticCheck
    repo,state,_,_=prepared
    material=state.materials[0]
    raw=SemanticCheck(target_id=state.claims[0].id,aspect='applicability',status='needs_reading',source_ids=['source-view-1'],rationale='Missing producer evidence',counterevidence=['Producer guarantee is unverified']).model_dump(mode='json')
    _,engine,_=make(tmp_path,prepared,[raw,patch('/source_ids',[material.id])])
    engine.state=state;engine.budget=BudgetTracker(engine.config.budget,state)
    import shutil
    shutil.copytree(repo,engine.root/'source')
    result,_=engine.ask('semantic_review',SemanticCheck,{'materials':[material.model_dump(mode='json')]*2})
    assert result.source_ids==[material.id] and result.counterevidence==raw['counterevidence']
    session=next(iter(state.repair_sessions.values()))
    assert json.loads(Path(session['original_path']).read_text())['source_ids']==['source-view-1']
    assert session['status']=='accepted' and state.usage['agent_calls']==2


def test_covered_citation_uses_cached_read_without_agent_repair(tmp_path,prepared):
    import shutil
    from consensus_assurance.core.types import SemanticCheck
    repo,state,_,_=prepared
    reply=SemanticCheck(target_id=state.claims[0].id,aspect='applicability',status='needs_reading',source_ids=['counter.py:2:3'],rationale='Inspect this actual interval',counterevidence=['Unknown caller guarantee'])
    _,engine,_=make(tmp_path,prepared,[reply.model_dump(mode='json')])
    engine.state=state;engine.budget=BudgetTracker(engine.config.budget,state)
    shutil.copytree(repo,engine.root/'source')
    before=dict(state.usage)
    result,_=engine.ask('semantic_review',SemanticCheck,{'materials':[m.model_dump(mode='json') for m in state.materials]})
    assert result.source_ids==['counter.py:2:3'] and result.counterevidence==reply.counterevidence
    assert any(m.id=='counter.py:2:3' for m in state.materials)
    assert not state.repair_sessions and state.usage['agent_calls']==1
    assert state.usage.get('targeted_reads',0)==before.get('targeted_reads',0)
    receipt=list(state.read_plans.values())[-1]
    assert all(i['status']=='cached' and i['new_chars']==0 for i in receipt['items'])


def test_same_family_references_are_repaired_together(tmp_path,prepared):
    repo,engine,_=make(tmp_path,prepared,[candidate(),{'replacements':[{'path':'/requests/0/start_line','value_json':'1'},{'path':'/requests/1/start_line','value_json':'1'}],'rationale':'Repair independent reference representations together'}])
    state=prepared[1];engine.state=state;engine.budget=BudgetTracker(engine.config.budget,state)
    import shutil
    shutil.copytree(repo,engine.root/'source')
    def check(reply):
        ds=[Diagnostic(code='audit_spec_reference',category='format',paths=[f'/requests/{i}/start_line'],allowed=['representation'],message='Invalid controlled reference') for i,q in enumerate(reply.requests) if q.start_line!=1]
        if ds:raise DiagnosticError(ds)
    reply,_=engine.ask('read',ReadingPlan,{},check)
    assert all(q.start_line==1 for q in reply.requests)
    assert state.usage['agent_calls']==2
