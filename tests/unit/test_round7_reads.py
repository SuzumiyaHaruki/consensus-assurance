"""Source plans use real snapshot metadata, unique accounting and durable receipts."""
import pytest
from consensus_assurance.core.config import Budget
from consensus_assurance.core.types import ReadRequest
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.materials import plan_read,apply_read,material_usage,preflight
from consensus_assurance.adapters.storage.snapshot import capture
from test_round6_boundaries import controller


def request(file,a,b):return ReadRequest(file=file,start_line=a,end_line=b,reason='Inspect an actual dependency')


@pytest.mark.parametrize('tail',[False,True])
def test_invalid_batch_before_or_after_valid_is_atomic(prepared,tail):
    repo,state,_,_=prepared;state.materials=[]
    valid=request('counter.py',1,2);bad=request('limits.py',1,3)
    before=state.model_dump()
    with pytest.raises(DiagnosticError) as caught:plan_read(state,repo,[valid,bad] if tail else [bad,valid],Budget())
    assert state.model_dump()==before
    d=caught.value.diagnostics[0]
    assert d.code=='read_range' and d.details['file_metadata']['lines']==2
    assert d.details['original_request']['end_line']==3


@pytest.mark.parametrize('content,good,bad',[(b'a\r\nb\r\n',(2,2),(2,3)),(b'',None,(1,1)),(b'a\n',(1,1),(2,2))])
def test_actual_eof_crlf_and_empty_file(prepared,content,good,bad):
    repo,state,_,_=prepared;(repo/'edge.txt').write_bytes(content);state.snapshot=capture(repo)
    if good:assert preflight(state,repo,[request('edge.txt',*good)])
    with pytest.raises(DiagnosticError):preflight(state,repo,[request('edge.txt',*bad)])


def test_denied_path_and_bad_encoding_are_distinct(prepared):
    repo,state,_,_=prepared
    with pytest.raises(DiagnosticError) as caught:preflight(state,repo,[request('../private.txt',1,1)])
    assert caught.value.diagnostics[0].code=='read_permission'
    (repo/'raw.txt').write_bytes(b'\xff\xfe');state.snapshot=capture(repo)
    # A declared readable input must still pass the decoder, even for imported metadata.
    state.snapshot.readable_files.append('raw.txt')
    with pytest.raises(DiagnosticError) as caught:preflight(state,repo,[request('raw.txt',1,1)])
    assert caught.value.diagnostics[0].code=='read_encoding'


def test_breadth_defers_large_plan_and_depth_gets_small_dependency(prepared):
    repo,state,_,_=prepared
    (repo/'large.txt').write_text('L'*700+'\n');(repo/'small.txt').write_text('s'*199+'\n');state.snapshot=capture(repo)
    state.materials=[];state.material_allocations=[]
    budget=Budget(material_chars=1000)
    receipt,new=plan_read(state,repo,[request('large.txt',1,1)],budget,purpose='breadth',partial=True)
    assert receipt.status=='deferred';apply_read(state,receipt,new)
    depth,mat=plan_read(state,repo,[request('small.txt',1,1)],budget,purpose='depth')
    assert depth.status=='complete';apply_read(state,depth,mat)
    # Breadth still has a reserved share; it is not silently deleted from the agenda.
    assert state.read_plans[receipt.id]['items'][0]['status']=='deferred'
    assert material_usage(state)['unique_chars']==200
    small,_=plan_read(state,repo,[request('small.txt',1,1)],Budget(material_chars=200),purpose='breadth')
    assert small.items[0].status=='cached'


def test_overlap_contained_and_adjacent_ranges_only_charge_union(prepared):
    repo,state,_,_=prepared;state.materials=[];state.material_allocations=[]
    budget=Budget()
    for a,b in [(1,2),(3,5),(1,5),(2,4),(4,8)]:
        result,materials=plan_read(state,repo,[request('counter.py',a,b)],budget)
        apply_read(state,result,materials)
    used=material_usage(state)['unique_chars']
    assert used==sum(len(x)+1 for x in (repo/'counter.py').read_text().splitlines()[:8])
    assert sum(a['new_chars'] for a in state.material_allocations)==used


@pytest.mark.parametrize('point',['before_commit','after_receipt','manifest'])
def test_read_interrupt_resume_is_idempotent(tmp_path,prepared,point):
    repo,state,_,_=prepared;state.materials=[];state.read_plans={};state.material_allocations=[]
    e=controller(tmp_path,state)
    # Use the current snapshot's authorized source; controller tests need no tool execution.
    e.root.mkdir(parents=True,exist_ok=True)
    def hook(stage,*args):
        if stage==point:raise RuntimeError('Injected read interruption')
    e.read_commit_hook=hook
    if point=='manifest':e.graph_commit_hook=lambda key:hook('manifest')
    req=[request('counter.py',1,2)]
    with pytest.raises(RuntimeError):e.read(req,plan_id='stable-plan')
    e.read_commit_hook=lambda *a:None;e.graph_commit_hook=lambda *a:None
    result=e.read(req,plan_id='stable-plan')
    assert result['status']=='complete' and e.state.usage['targeted_reads']==1
    used=material_usage(state);e.read(req,plan_id='stable-plan')
    assert material_usage(state)==used and len(state.reading_history)==2 # prepared fixture history plus this plan
    with pytest.raises(ValueError):e.read([request('counter.py',1,3)],plan_id='stable-plan')


def test_partial_receipt_never_claims_unmet_range_complete(tmp_path,prepared):
    repo,state,_,_=prepared;state.materials=[];state.read_plans={};state.material_allocations=[]
    e=controller(tmp_path,state);e.root.mkdir(parents=True,exist_ok=True)
    e.config.budget.material_chars=100;e.config.budget.breadth_material_reserve=0
    result=e.read([request('limits.py',1,2),request('counter.py',1,10)],plan_id='partial')
    assert result['status']=='partial'
    assert [x['status'] for x in result['items']]==['acquired','deferred']
    again=e.read([request('limits.py',1,2),request('counter.py',1,10)],plan_id='partial')
    assert again['status']=='partial' and again['items'][0]['status']=='cached'
    assert state.usage['targeted_reads']==1


def test_blank_lines_remain_in_unique_range_accounting(prepared):
    repo,state,_,_=prepared;(repo/'blank.txt').write_text('\n\n\n');state.snapshot=capture(repo);state.materials=[];state.material_allocations=[]
    receipt,items=plan_read(state,repo,[request('blank.txt',1,3)],Budget())
    apply_read(state,receipt,items)
    assert material_usage(state)=={'unique_chars':3,'unique_chunks':1}
    again,_=plan_read(state,repo,[request('blank.txt',2,3)],Budget())
    assert again.items[0].status=='cached'
