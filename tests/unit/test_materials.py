"""Source plans use real snapshot metadata, unique accounting and durable receipts."""
import pytest
from consensus_assurance.core.config import Budget
from consensus_assurance.core.types import ReadRequest
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.materials import plan_read,apply_read,material_usage,preflight
from consensus_assurance.adapters.storage.snapshot import capture
from test_graph_mutations import controller


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


def test_lookup_reads_shifted_definition_and_reports_ambiguity(prepared):
    repo,state,_,_=prepared
    (repo/'moved.go').write_text(''.join(f'func unrelated{i}() {{}}\n' for i in range(9))+
        'type Alpha struct{}\ntype Beta struct{}\nfunc (a *Alpha) Handle() {}\nfunc (b *Beta) Handle() {}\nvar initialized = 7\n')
    state.snapshot=capture(repo)
    def find(**kwargs):return ReadRequest(reason='Locate actual source',**kwargs)
    receipt,items=plan_read(state,repo,[find(symbol='Alpha.Handle'),find(literal='var initialized = 7')],Budget())
    assert receipt.status=='complete' and all(i.status=='acquired' for i in receipt.items)
    assert items[0].start_line>6 and items[0].text.startswith('func (a *Alpha) Handle()')
    assert items[1].text=='var initialized = 7'
    ambiguous,_=plan_read(state,repo,[find(symbol='Handle'),find(symbol='Absent')],Budget())
    assert [i.status for i in ambiguous.items]==['unresolved','unresolved']
    assert [i.file_metadata['lookup']['match_count'] for i in ambiguous.items]==[2,0]
    with pytest.raises(DiagnosticError):preflight(state,repo,[find(file='../private.go',symbol='Handle')])


def test_lookup_defer_and_unresolved_are_reportable(tmp_path,prepared):
    from consensus_assurance.reporting.chinese import resource_lines
    repo,state,_,_=prepared
    (repo/'large.py').write_text('def selected():\n'+'    value = 1\n'*25+'    return value\n')
    state.snapshot=capture(repo);state.materials=[]
    wanted=ReadRequest(symbol='selected',reason='Read the complete selected definition')
    receipt,items=plan_read(state,repo,[wanted],Budget(material_chars=100))
    assert receipt.status=='deferred' and receipt.items[0].status=='deferred'
    apply_read(state,receipt,items)
    assert 'selected' in '\n'.join(resource_lines(state)) and '定位 large.py:1–27' in '\n'.join(resource_lines(state))
    missing,_=plan_read(state,repo,[ReadRequest(symbol='absent',reason='Locate the absent definition')],Budget())
    assert missing.items[0].status=='unresolved' and not missing.items[0].material_ids
    from consensus_assurance.workflow.materials import read_complete
    assert missing.status=='complete' and not read_complete(missing.model_dump(mode='json'))
    apply_read(state,missing,[])
    assert '查询未解决' in '\n'.join(resource_lines(state))


def test_qualified_python_and_go_member_lookup(prepared):
    repo,state,_,_=prepared
    (repo/'members.py').write_text('class One:\n    def run(self):\n        return 1\nclass Two:\n    def run(self):\n        return 2\n')
    (repo/'members.go').write_text('package sample\ntype Reader interface {\n    Read() error\n}\nconst (\n    First = 1\n    Second = 2\n)\n')
    state.snapshot=capture(repo)
    queries=[ReadRequest(symbol=name,reason='Locate full owner context') for name in ('One.run','Reader.Read','Second')]
    receipt,items=plan_read(state,repo,queries,Budget())
    assert all(i.status=='acquired' for i in receipt.items)
    assert items[0].text.startswith('    def run') and 'return 1' in items[0].text
    assert items[1].text.startswith('type Reader interface') and 'Read() error' in items[1].text
    assert items[2].text.startswith('const (') and 'Second = 2' in items[2].text
    (repo/'unfinished.go').write_text('package sample\nconst (\n    Open = 1\n')
    state.snapshot=capture(repo)
    unfinished,_=plan_read(state,repo,[ReadRequest(file='unfinished.go',symbol='Open',reason='Check declaration boundary')],Budget())
    assert unfinished.items[0].status=='unresolved' and 'no complete boundary' in unfinished.items[0].reason


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


def test_partial_receipt_never_claims_unmet_range_complete(tmp_path,prepared):
    repo,state,_,_=prepared;state.materials=[];state.read_plans={};state.material_allocations=[]
    e=controller(tmp_path,state);e.root.mkdir(parents=True,exist_ok=True)
    e.config.budget.material_chars=100;e.config.budget.breadth_material_reserve=0
    result=e.read([request('limits.py',1,2),request('counter.py',1,10)],plan_id='partial')
    assert result['status']=='partial'
    assert [x['status'] for x in result['items']]==['acquired','deferred']
    again=e.read([request('limits.py',1,2),request('counter.py',1,10)],plan_id='partial')
    assert again['status']=='partial' and again['items'][0]['status']=='cached'


def test_blank_lines_remain_in_unique_range_accounting(prepared):
    repo,state,_,_=prepared;(repo/'blank.txt').write_text('\n\n\n');state.snapshot=capture(repo);state.materials=[];state.material_allocations=[]
    receipt,items=plan_read(state,repo,[request('blank.txt',1,3)],Budget())
    apply_read(state,receipt,items)
    assert material_usage(state)=={'unique_chars':3,'unique_chunks':1}
    again,_=plan_read(state,repo,[request('blank.txt',2,3)],Budget())
    assert again.items[0].status=='cached'


def test_report_attributes_calls_and_acquisition_by_saved_identity(prepared):
    from consensus_assurance.core.types import CheckRun,InquiryTask
    from consensus_assurance.reporting.chinese import resource_lines
    _,state,_,_=prepared;unit=state.units[0]
    call=CheckRun(action='agent',cwd='.',snapshot_id=state.snapshot.id)
    state.checks=[call]
    task=InquiryTask(id='focused-review',kind='review',reason='Review the selected obligation',trigger='unit',unit_id=unit.id,check_id=call.id)
    state.inquiry_tasks=[task]
    state.packet_receipts=[{'status':'executed','check_id':call.id,'kind':'semantic_review','task_id':task.id,'unit_id':unit.id,'source_chars_sent':37}]
    state.material_allocations=[{'plan_id':'other','new_chars':23,'purpose':'breadth'}, {'plan_id':'focused','new_chars':17,'purpose':'depth'}]
    state.reading_history=[{'plan_id':'focused','related_ids':[unit.id]}, {'plan_id':'other','related_ids':['A1']}]
    lines=resource_lines(state)
    assert any(f'unit:{unit.id} | 1 | 0 | 17 | 37 |' in line for line in lines)
    assert not any('unknown:unattributed | 1 |' in line for line in lines)


import json,shutil
import pytest
from consensus_assurance.core.types import Material
from consensus_assurance.workflow.sources import covered,includes
from consensus_assurance.workflow.output_repair import diagnostic_context,OutputRepair
from consensus_assurance.core.diagnostics import Diagnostic
from consensus_assurance.workflow.repair_policy import validate_representation
from test_graph_mutations import controller


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
    item={'target_id':'b','aspect':'applicability','status':'disputed','limitations':['Storage uncertain'],'source_ids':['alias'],'rationale':'The producer guarantee lacks support'}
    after={**item,'aspect':'decomposition','source_ids':['actual']}
    validate_representation({'items':[item]},{'items':[after]},[{'path':'/items/0'}],{})
    with pytest.raises(ValueError):validate_representation({'items':[item]},{'items':[{**after,'status':'no_issue_found'}]},[{'path':'/items/0'}],{})
    with pytest.raises(ValueError):validate_representation({'items':[item]},{'items':[{**after,'limitations':[]}]},[{'path':'/items/0'}],{})


@pytest.mark.parametrize('case,code',[('unknown','issue_unknown_source'),('omitted','issue_context_not_provided'),('citation','issue_citation_missing')])
def test_issue_source_failures_have_distinct_actions(prepared,case,code):
    from test_semantic_review import setup
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
    from test_repair_sessions import make,candidate,patch
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
    assert session['attempt']==2


@pytest.mark.parametrize('document', ['# Contract\nAll fixture promises on one line.\n', '# Contract\n\nFirst promise.\nSecond promise.\n\nLast promise.\n'])
def test_synthetic_whole_document_citations_follow_actual_layout(tmp_path, document):
    from regression_support import toy_responses
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.materials import read_material, ReadRequest
    (tmp_path/'README.md').write_text(document)
    responses=toy_responses(tmp_path)
    request=next(r for r in responses[0]['requests'] if r['file']=='README.md')
    material=read_material(tmp_path,capture(tmp_path),ReadRequest.model_validate(request))
    assert material.end_line==len(document.splitlines())
    assert material.text=="\n".join(document.splitlines())
    assert responses[1]['claims'][0]['grounding']['expectation_ids']==[material.id]
    assert next(r for r in responses[0]['requests'] if r['file']=='counter.py')['end_line']==10
