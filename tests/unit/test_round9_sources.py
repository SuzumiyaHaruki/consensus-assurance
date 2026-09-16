import json,shutil
import pytest
from consensus_assurance.core.types import Material
from consensus_assurance.workflow.sources import covered,includes
from consensus_assurance.workflow.output_repair import diagnostic_context,OutputRepair
from consensus_assurance.core.diagnostics import Diagnostic
from consensus_assurance.workflow.repair_policy import validate_representation
from test_round6_boundaries import controller


def test_reference_alias_overlap_and_content_version(prepared):
    _,s,_,_=prepared;m=s.materials[0]
    left=m.model_copy(update={'id':'left','end_line':m.start_line})
    right=m.model_copy(update={'id':'right','start_line':m.start_line+1})
    assert covered(m,[left,right])
    assert not covered(m,[left,right.model_copy(update={'content_digest':'other-version'})])
    assert not covered(m,[left])


def test_requested_sources_precede_old_closure(prepared):
    _,s,_,_=prepared;new=s.materials[-1];old=s.materials[0]
    d=Diagnostic(code='missing',category='material',object_ids=['c'],material_ids=[old.id],message='Missing current source')
    context={'materials':[m.model_dump(mode='json') for m in s.materials],'repair_requested_material_ids':[new.id]}
    result=diagnostic_context({'claims':[{'id':'c','source_ids':[old.id]}]},[d],context,len(json.dumps(new.model_dump()))+450)
    assert new.id in {m['id'] for m in result['materials']}
    assert not result['required_materials_missing']


def test_negative_item_metadata_can_change_not_judgment():
    item={'target_id':'b','aspect':'applicability','status':'disputed','explanation':'The producer guarantee lacks support','limitations':['Storage uncertain'],'source_ids':['alias']}
    after={**item,'aspect':'decomposition','source_ids':['actual']}
    validate_representation({'items':[item]},{'items':[after]},[{'path':'/items/0'}],{})
    with pytest.raises(ValueError):validate_representation({'items':[item]},{'items':[{**after,'status':'no_issue_found'}]},[{'path':'/items/0'}],{})
    with pytest.raises(ValueError):validate_representation({'items':[item]},{'items':[{**after,'limitations':[]}]},[{'path':'/items/0'}],{})


def test_two_new_four_cached_then_third_dependency_with_same_quota(tmp_path,prepared):
    repo,s,_,_=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source')
    s.materials=[];s.material_allocations=[];s.read_plans={};s.usage={};e.config.budget.targeted_reads=3
    for n,(file,a,b) in enumerate([('counter.py',1,1),('counter.py',2,2)]):
        assert e.read([dict(file=file,start_line=a,end_line=b,reason='New actual source')],plan_id='new-'+str(n))['status']=='complete'
    for n in range(4):assert e.read([dict(file='counter.py',start_line=1,end_line=2,reason='Use a combined cached view')],plan_id='cache-'+str(n))['status']=='complete'
    q=[dict(file='limits.py',start_line=1,end_line=2,reason='Third necessary dependency')]
    assert e.read(q,plan_id='third')['status']=='complete'
    assert s.usage['targeted_reads']==3
    assert e.read(q,plan_id='third')['status']=='complete' and s.usage['targeted_reads']==3


def test_deferred_plan_does_not_spend_source_quota(tmp_path,prepared):
    repo,s,_,_=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source')
    s.materials=[];e.config.budget.material_chars=0
    receipt=e.read([dict(file='limits.py',start_line=1,end_line=2,reason='Needed source')],plan_id='pending')
    assert receipt['status']=='deferred' and not s.usage.get('targeted_reads')


@pytest.mark.parametrize('case,code',[('unknown','issue_unknown_source'),('omitted','issue_context_not_provided'),('citation','issue_citation_missing')])
def test_issue_source_failures_have_distinct_actions(prepared,case,code):
    from test_round8_review_context import setup
    from consensus_assurance.workflow.reviews import validate_resolutions
    s,t,r=setup(prepared);resolution=r.resolutions[0]
    t.material_ids=[m.id for m in s.materials];t.context_receipt_id='actual-test-packet'
    if case=='unknown':resolution.source_ids=['not-acquired']
    elif case=='omitted':t.material_ids=[m.id for m in s.materials if m.id not in resolution.source_ids]
    else:
        for item in r.items:item.source_ids=[next(m.id for m in s.materials if m.id not in resolution.source_ids and m.file!='README.md')]
    with pytest.raises(ValueError) as caught:validate_resolutions(s,t,r)
    d=caught.value.diagnostics[0]
    assert d.code==code
    if case=='citation':assert d.allowed==['representation'] and all('/source_ids' in p for p in d.paths)


@pytest.mark.parametrize('interrupted',[False,True])
def test_explicit_requested_range_is_in_actual_next_repair_packet(tmp_path,prepared,interrupted):
    from test_round6_repair_sessions import make,candidate,patch
    from consensus_assurance.workflow.materials import ReadingPlan
    from consensus_assurance.core.diagnostics import DiagnosticError
    source='limits.py:1:2'
    responses=[candidate(),{'requests':[dict(file='limits.py',start_line=1,end_line=2,reason='Need exact producer source')],'rationale':'Attach current evidence'},patch('/requests/0/start_line',1)]
    repo,e,_=make(tmp_path,prepared,responses)
    def validate(plan):
        if plan.requests[0].start_line!=1:raise DiagnosticError([Diagnostic(code='location',category='location',paths=['/requests/0/start_line'],message='Correct the bound using producer code',allowed=['representation','read'])])
    # start() establishes the source snapshot; acquire the fixture ranges in execute.
    def execute(**kwargs):
        e.state.materials=prepared[1].materials
        return e.ask('read',ReadingPlan,{},validate)
    e.execute=execute
    checkpoint=e.checkpoint
    crashed=False
    def checkpoint_once(event):
        nonlocal crashed
        checkpoint(event)
        if interrupted and not crashed and event=='action_result_saved' and e.state.pending_action.kind=='agent:read:repair':
            crashed=True;raise RuntimeError('Recorded attachment request, before reading receipt')
    e.checkpoint=checkpoint_once
    if interrupted:
        with pytest.raises(RuntimeError):e.start(repo)
        e.resume()
    else:e.start(repo)
    assert e.state.usage['agent_calls']==3
    session=next(iter(e.state.repair_sessions.values()))
    from consensus_assurance.workflow.sources import all_materials
    packets=[json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1]) for p in e.root.glob('agent/*/prompt.txt')]
    final=next(p for p in packets if p.get('related_context',{}).get('required_material_ids'))
    assert source in {m['id'] for m in all_materials(final)}
    assert e.state.usage.get('targeted_reads',0)==0 and session['attempt']==2
