"""Bounded read-only feedback over synthetic records; no investigation loop required."""
import json
import pytest
from support.evidence import saved_evidence, research_state, append_interpretation
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.workflow.research import execution_feedback, operation_summary, excerpt


@pytest.mark.parametrize('large',['many_events','large_value','missing_long_identity','repeated_diagnostics'])
def test_execution_feedback_omits_whole_large_event_sets_without_rewriting_receipts(tmp_path,large):
    events = [dict(event='admitted', operation='one', value=3, limit=3),
              dict(event='returned', operation='one', value=0)]
    events += {
        'many_events': [*[dict(event='extra', operation=str(i)) for i in range(9)], 'not-json'],
        'large_value': [dict(event='extra', operation='large', value='x'*7000)],
        'missing_long_identity': [dict(event=name, operation='x'*7000) for name in ('admitted', 'returned')],
        'repeated_diagnostics': [dict(event=name, operation=str(i), limit=3)
            for i in range(12) for name in ('admitted', 'returned')],
    }[large]
    state, fixed, check = saved_evidence(tmp_path, events=events)
    before = state.model_dump(mode='json')
    saved = {p: p.read_bytes() for p in (tmp_path/'logs').rglob('*') if p.is_file()}
    value = execution_feedback(state, tmp_path, fixed, check)
    raw=json.loads((tmp_path/value['observations']).read_text())
    assert value['events']==[] and value['event_count']==value['events_omitted_count']==len(raw['events'])
    assert value['comparisons'][0]['result']['valid_witness_indices']==[1]
    assert value['comparisons'][0]['result']['evaluated_indices']==[1]
    if large=='missing_long_identity':
        assert value['comparisons'][0]['result']['missing_indices']
        assert value['comparisons'][0]['omitted_detail_counts']['diagnostics']>0
        assert 'x'*7000 not in json.dumps(value)
    if large in {'missing_long_identity','repeated_diagnostics'}:
        assert value['diagnostic_summary'] and not value['diagnostic_groups_omitted']
        diagnostic=value['diagnostic_summary'][0]
        assert diagnostic['comparison_index']==0 and 'Missing' in diagnostic['reason']
        location=diagnostic['locations'][0]
        assert location['output_location']==raw['events'][location['event_index']]['_ca_observation']['location']
        if large=='repeated_diagnostics':
            assert diagnostic['occurrences']==12 and len(diagnostic['locations'])==3
            assert len(json.dumps(value['diagnostic_summary']))<4000
    assert state.model_dump(mode='json')==before
    assert all(p.read_bytes()==data for p,data in saved.items())
    indices=[1] if large in {'many_events','repeated_diagnostics'} else [1,len(raw['events'])-1]
    append_interpretation(state, conclusion='conditional', executions={value['id']:indices})
    value=operation_summary(state,tmp_path)['interpretation_changes'][0]['executions'][0]
    raw=json.loads((tmp_path/value['observations']).read_text())
    assert value['cited_events']==[{'event_index':1,'observation':raw['events'][1]}]
    assert value['omitted_cited_indices']==([] if large in {'many_events','repeated_diagnostics'} else [len(raw['events'])-1])
    assert value['parsing_error_count']==len(raw['parsing_errors'])==int(large=='many_events')
    assert value['prerequisites']==raw['prerequisites']
    comparison=value['comparisons'][0]
    assert comparison['outcome']==raw['comparisons'][0]['outcome']
    if large=='missing_long_identity':
        assert comparison['missing_indices'] and not comparison['comparison_complete']
        assert comparison['diagnostic_count']>0 and comparison['limitation_count']>0
    if large=='repeated_diagnostics':
        assert value['diagnostic_summary'][0]['occurrences']==12
    assert 'Explicitly cited subset' in value['selection'] and 'x'*7000 not in json.dumps(value)


def test_changed_citation_remains_visible_when_unchanged_citations_fill_inline_limit(tmp_path):
    events = [dict(event='admitted', operation='one', value=3, limit=3),
              dict(event='returned', operation='one', value=0)]
    events += [dict(event='extra', operation=str(i)) for i in range(9)]
    state, fixed, check = saved_evidence(tmp_path, events=events)
    for count in (8, 9):
        append_interpretation(state, conclusion='conditional', executions={check.id:list(range(count))})
    change=operation_summary(state,tmp_path)['interpretation_changes'][0]
    assert change['text_changes']==[]  # Only the receipt indices changed.
    receipt=change['executions'][0]
    assert receipt['previous_event_indices']==list(range(8)) and receipt['current_event_indices']==list(range(9))
    assert receipt['cited_events'][0]['event_index']==8 and len(receipt['cited_events'])==8
    assert receipt['omitted_cited_indices']==[7] and receipt['event_indices']==list(range(9))


def test_navigation_keeps_evidence_references_and_marks_long_prose_without_mutating_records(tmp_path):
    from consensus_assurance.core.types import KnowledgeEntry
    from consensus_assurance.workflow.research import current_view, preview
    state = research_state(tmp_path)
    entry=KnowledgeEntry(id='projection-entry',kind='behavior',operation_id='projection',
        statement='A bounded observation with several supporting records',
        conditions='The observation applies only within its recorded invocation interval. '*12,
        source_ids=[f'source-{i}' for i in range(8)],executions={f'receipt-{i}':[i] for i in range(4)})
    state.knowledge.append(entry)
    write_json(tmp_path/'state.json', state)
    saved=(tmp_path/'state.json').read_bytes()
    before=state.model_dump(mode='json')
    current=current_view(state,tmp_path)
    summary=operation_summary(state,tmp_path)
    item=current['knowledge'][0]
    assert item['source_ids']==entry.source_ids and item['executions']==entry.executions
    assert '[preview:' in item['conditions'] and 'characters omitted; see full record]' in item['conditions']
    assert item['conditions'].count('[preview:')==1 and preview(item)==item
    for item in (item,current['reselection']['knowledge'][0],summary['reselection']['knowledge'][0]):
        assert item['conditions']==excerpt(entry.conditions)
        locator=item['record']
        complete=json.loads((tmp_path/locator['path']).read_text())[locator['collection']]
        assert item['view']=='preview'
        assert next(record for record in complete if record['id']==locator['id'])==entry.model_dump(mode='json')
    assert state.model_dump(mode='json')==before and (tmp_path/'state.json').read_bytes()==saved


@pytest.mark.parametrize('before,after,chars',[
    ('A café result\nrequires support.', 'A café result\nrequires independent support.',4000),
    (['Repeated','Other','Repeated'], ['Repeated','Repeated','Other'],4000),
    (['prefix '*300+'old measurement'+' suffix'*300], ['prefix '*300+'new measurement'+' suffix'*300],4000),
    ('x'*48+'old'+'y'*48, 'x'*48+'new'+'y'*48,40),
])
def test_text_changes_preserve_exact_ranges_order_and_changed_context(before,after,chars):
    from consensus_assurance.workflow.research import text_changes
    prior,current={'limitations':before},{'limitations':after}
    saved=json.dumps([prior,current])
    budget={'chars':chars,'edits':12,'work':1000000}
    change,=text_changes(prior,current,('limitations',),budget)
    assert change['display']=='diff' and not change['omitted_edits']
    assert change['format']==('text' if isinstance(after,str) else 'json')
    old,new=(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
        for value in (before,after))
    restored,cursor='',0
    for edit in change['edits']:
        a,b=edit['before']['range'];c,d=edit['after']['range']
        restored+=old[cursor:a]+new[c:d];cursor=b
        for side,value in (('before',old),('after',new)):
            part=edit[side];start,end=part['context_range'];fragment=value[start:end]
            assert not part['omitted_characters'] and part['parts']==[fragment]
    assert restored+old[cursor:]==new and saved==json.dumps([prior,current])
    if isinstance(after,list) and 'new measurement' in after[0]:
        assert 'new measurement' in json.dumps(change) and 'old measurement' in json.dumps(change)
    if chars==40:
        assert 'old' in json.dumps(change) and 'new' in json.dumps(change)


@pytest.mark.parametrize('limit',['size','work'])
def test_text_changes_bound_matching_and_shared_output_without_hiding_omissions(monkeypatch,limit):
    import difflib
    from consensus_assurance.workflow.research import text_changes
    monkeypatch.setattr(difflib,'SequenceMatcher',lambda *a,**k:pytest.fail('Unbounded matching'))
    n=21000 if limit=='size' else 100
    old={'rationale':'a'*n,'limitations':['Unchanged','Keep this condition']}
    new={'rationale':'b'*n,'limitations':['Unchanged']}
    budget={'chars':120,'edits':1,'work':1000000 if limit=='size' else 0}
    first,second=text_changes(old,new,tuple(old),budget)
    assert first['display']=='bounded_replacement' and first['edits']
    for side in first['edits'][0].values():
        assert len(side['parts'])==2 and side['omitted_characters']==n-sum(map(len,side['parts']))
    assert second['field']=='limitations' and second['omitted_edits'] and not second['edits']
    third,=text_changes(None,{'statement':'A new account'},('statement',),budget)
    assert third['omitted_edits'] and not third['edits']
    assert budget['chars']==0 and budget['edits']==0
    assert text_changes(new,new,tuple(new),budget)==[]


def test_reselection_keeps_old_open_gaps_and_recent_explanations_visible(tmp_path):
    from consensus_assurance.core.types import Gap, Interpretation
    from consensus_assurance.workflow.research import current_view
    state = research_state(tmp_path)
    old = state.investigations[0]
    state.investigations += [old.model_copy(update={'id': f'question-{n}',
        'question': f'Which return condition applies to caller {n}?'}) for n in range(9)]
    pending = state.investigations[1]
    pending.gaps = [Gap(id='caller', operation_id='revisit', question='Which producer establishes the caller bound?')]
    counterevidence = [f'The documented caller condition {n} bounds the sampled input' for n in range(5)]
    limitations = [f'No observation establishes asynchronous completion for caller {n}' for n in range(5)]
    counterevidence[1] += '; the actual operand comes from the admitted caller' * 8
    limitations[4] += '; downstream recovery remains outside this observation' * 8
    prior = Interpretation(id='prior', operation_id='start', investigation_id=old.id, source_ids=['code'],
        conclusion='unresolved', rationale='The initial caller contract still needs inspection')
    current = Interpretation(id='current', operation_id='revisit', investigation_id=old.id, source_ids=['code'],
        conclusion='explained', defect_claim='refuted', rationale='The local return is explained by the boundary branch',
        counterevidence=counterevidence, limitations=limitations)
    state.interpretations = [prior, current]
    state.current_submission = dict(phase='accepted', operation_id='revisit')
    before = state.model_dump(mode='json')
    local, = operation_summary(state, tmp_path)['questions']
    assert local['id'] == old.id and state.model_dump(mode='json') == before
    answer = local['latest_interpretation']
    assert answer['counterevidence'] == [excerpt(v) for v in counterevidence[:3]]
    assert answer['limitations'] == limitations[:3]
    assert answer['counterevidence_omitted_count'] == answer['limitations_omitted_count'] == 2
    assert answer['record'] == dict(path='state.json', collection='interpretations', id=current.id)
    assert answer['defect_claim'] == 'refuted' and answer['conclusion'] == 'explained'
    state.investigations.append(old.model_copy(update={'id': 'new', 'operation_id': 'another',
        'question': 'Which recovery caller uses this return?'}))
    state.current_submission = dict(phase='accepted', operation_id='another')
    before = state.model_dump(mode='json')
    local, = operation_summary(state, tmp_path)['questions']
    assert local['id'] == 'new' and local['latest_interpretation'] is None
    index = current_view(state, tmp_path)
    questions = {q['id']: q for q in index['reselection']['questions']}
    assert list(questions) == [q.id for q in state.investigations]
    assert questions[pending.id]['open_gap_count'] == 1
    retained = index['investigations'][0]
    assert retained['discriminator'] == old.discriminator and retained['hypothesis'] == old.hypothesis
    assert retained['latest_interpretation'] == answer
    assert all(q['disposition'] == 'active' for q in questions.values()) and not state.experiments
    assert state.model_dump(mode='json') == before
