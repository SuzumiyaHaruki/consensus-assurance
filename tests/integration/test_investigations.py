"""Method continuity through the normal loop; supplied fixture expectations are not discovery evidence."""
import json
from pathlib import Path
import pytest
from audit_support import engine_for, first, combined, experiment, opinion, stop
from consensus_assurance.core.submissions import AuditSubmission
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import open_gaps


def test_combined_local_start_and_interpretation_feedback(tmp_path):
    seen = []
    def interpret(state):
        seen.append(json.loads((e.root/'research.json').read_text()))
        return opinion(state)
    def finish(state):
        index = json.loads((e.root/'research.json').read_text())
        assert index['investigations'][0]['latest_execution'] == seen[0]['investigations'][0]['latest_execution']
        assert index['investigations'][0]['latest_interpretation']['executions']
        return stop(state)
    e, repo = engine_for(tmp_path,[combined,interpret,finish])
    state = e.start(repo)
    assert len(state.investigations) == len(state.experiments) == len(state.interpretations) == 1
    assert state.usage == {'agent_calls':3,'experiments':1}
    assert state.agent_session_id == 'fixture-session'
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id == fixed.id)
    result = assessment(state,e.root,fixed,check)
    assert result['outcome'] == 'violated' and not result['confirmed']
    assert result['comparisons'][0]['valid_witness_indices'] == [1]
    assert not any(name in type(state).model_fields for name in ('units','claims','bindings','relations','evidence','findings'))


def test_source_only_answer_and_exact_noop_keep_cost_without_revisions(tmp_path):
    def answer(state):
        q=state['investigations'][0]['id']
        return {'rationale':'Existing sources explain this local branch',
            'investigations':[{'id':q,'disposition':'explained','counterevidence':['Capacity branch handles the stated case']}],
            'interpretations':[dict(investigation_id=q,source_ids=['code','doc'],conclusion='explained',
                                    rationale='The boundary branch is directly visible in the cited source')]},{}
    seen=[]
    def duplicate(state):
        seen.append(state)
        return answer(state)
    def finish(state):
        assert state['current_submission']['no_change']
        assert state['investigations']==seen[0]['investigations']
        assert state['interpretations']==seen[0]['interpretations']
        return stop(state)
    e,repo=engine_for(tmp_path,[first,answer,duplicate,finish])
    state=e.start(repo)
    assert state.usage['agent_calls']==4 and state.usage.get('experiments',0)==0
    assert len(list((e.root/'submissions').glob('*/raw.json')))==3


def test_necessary_gap_survives_approval_and_local_child(tmp_path):
    def start(state):
        sub,files=combined(state)
        sub['gaps']=[dict(investigation_id='@q',question='Does normal initialization reach this premise?')]
        return sub,files
    def child(state):
        q=state['investigations'][0]['id']
        return {'rationale':'Independent local child', 'investigations':[dict(ref='@child',parent_id=q,
            question='What does the return expression compute?',source_ids=['code'],disposition='explained')],
            'interpretations':[dict(investigation_id='@child',source_ids=['code'],conclusion='explained',
                rationale='The actual expression returns zero at capacity')]},{}
    def answer(state):
        gap=state['investigations'][0]['gaps'][0]['id']
        return opinion(state,answers={gap:'The cited local contract allows precisely this input; no distributed prefix is claimed'})
    seen=[]
    def before_answer(state):
        assert open_gaps(e.state,e.state.investigations[0].id)
        seen.append(e.state.model_copy(deep=True))
        return answer(state)
    e,repo=engine_for(tmp_path,[start,opinion,child,before_answer,stop])
    state=e.start(repo)
    assert not open_gaps(state,state.investigations[0].id)
    assert open_gaps(seen[0],seen[0].investigations[0].id)
    assert state.investigations[0].disposition=='active'
    assert len(state.experiments)==1


def test_source_paths_and_whole_draft_repair_are_atomic(tmp_path):
    def bad(state):
        sub,files=combined(state)
        sub['sources'][0]['file']='../outside.py'
        return sub,files
    def repaired(state):
        assert not state['investigations'] and not state['experiments']
        assert state['current_submission']['phase']=='rejected'
        return combined(state)
    e,repo=engine_for(tmp_path,[bad,repaired,stop])
    state=e.start(repo)
    assert len(state.experiments)==1 and state.usage['experiments']==1
    rejection=next((e.root/'submissions').glob('*/diagnostics.json'))
    raw=json.loads((rejection.parent/'raw.json').read_text())
    assert raw['sources'][0]['file']=='../outside.py'
    assert (rejection.parent/'inputs/check.py').is_file()


def test_revision_needs_own_execution_but_interpretation_correction_does_not(tmp_path):
    def revise(state):
        a=state['experiments'][-1]
        request,files=experiment(a['investigation_id'])
        request.update(previous_id=a['id'],revision_reason='Correct the expected return from the boundary contract')
        request['comparisons'][0]['assertion']={'field':'value','value':0}
        return {'rationale':'Use a successor for the changed predicate','experiment':request},files
    def corrected(state):
        return opinion(state,conclusion='conditional',rationale='Existing observations do not establish the earlier interpretation')
    def duplicate(state):
        sub, files = revise(state)
        sub['experiment']['previous_id'] = state['experiments'][0]['id']
        return sub, files
    def finish(state):
        assert state['current_submission']['no_change']
        return stop(state)
    e,repo=engine_for(tmp_path,[combined,opinion,corrected,revise,duplicate,finish])
    state=e.start(repo)
    assert len(state.experiments)==2 and state.usage['experiments']==2
    old,new=state.experiments
    assert new.previous_id==old.id and 'comparisons' in new.difference
    old_check=next(c for c in state.checks if c.experiment_id==old.id)
    new_check=next(c for c in state.checks if c.experiment_id==new.id)
    assert assessment(state,e.root,old,old_check)['outcome']=='violated'
    assert assessment(state,e.root,new,new_check)['outcome']=='holds'
    assert assessment(state,e.root,new,new_check)['interpretation_id'] is None
    assert len(state.interpretations)==2


def research_case(state, protected=False, supplied=False):
    source=Path('tests/fixtures/research_protocol.py').read_text()
    sources=[dict(id='code',file='target.py',start_line=1,end_line=len(source.splitlines()),kind='code_observation'),
             dict(id='doc',file='README.md',start_line=1,end_line=1,kind='document_statement')]
    setup="ticket=(0,0)\nworker.pending.add(ticket)\nworker.reported.add(ticket)" if supplied else 'ticket=worker.begin()\nworker.report(ticket)'
    code=f'''import json
from target import Worker
worker=Worker(protected={protected!r})
{setup}
print('CA_EVENT '+json.dumps(dict(event='admitted',operation='one',epoch=worker.epoch)))
print('CA_EVENT '+json.dumps(dict(event='result',operation='one',epoch=worker.epoch,allowed=worker.allowed(ticket),finished=ticket in worker.finished)))
'''
    request=dict(investigation_id='@q',harness_path='check.py',source_ids=['code','doc'],
        scope={'description':'Notification and completion in one authority context','assumptions':['Supplied pending and reported sets'] if supplied else []},
        prefix='Supplied pending/report sets; no production history' if supplied else 'Construct Worker, call begin and report; observe allowed and finished',
        requirement='For a current admitted ticket, allowed implies finished',responsibility='The fixture caller contract explicitly separates report from finish',
        anchors=[dict(material_id='code',symbol='Worker.allowed',start_line=33,end_line=35)],
        prerequisites=[dict(alias='start',event='admitted')],
        comparisons=[dict(event='result',identity_fields=['operation','epoch'],admission_alias='start',
            antecedent={'field':'allowed','value':True},assertion={'field':'finished','value':True})])
    if state.get('investigations'):
        request['investigation_id']=state['investigations'][0]['id']
        request['previous_id']=state['experiments'][-1]['id']
        request['revision_reason']='Replace supplied state with the actual initializer and producer prefix'
        return {'rationale':'Investigate the registered missing history','experiment':request},{'check.py':code}
    sub={'rationale':'Separate produced notification from established completion','sources':sources,
        'knowledge':[dict(ref='@fact',kind='fact',statement='A recorded notification establishes completion',conditions='Current ticket',source_ids=['code','doc'])],
        'investigations':[dict(ref='@q',question='Does the decision guard require actual completion?',source_ids=['code','doc'],
            hypothesis='Notification may be consumed as completion',discriminator='Compare a real producer prefix and protected path',
            knowledge=[dict(entry_id='@fact',revision=1)]),
            dict(ref='@later',question='Does an authority transition retire the earlier ticket?',source_ids=['code'],knowledge=[dict(entry_id='@fact',revision=1)])],
        'gaps':[dict(investigation_id='@q',question='Was the critical notification established by actual producers?')],
        'experiment':request}
    return sub,{'check.py':code}


def test_conditional_probe_real_history_knowledge_correction_and_reuse(tmp_path):
    def initial(state):return research_case(state,supplied=True)
    def prefix(state):return research_case(state)
    def correct(state):
        q,later=state['investigations']
        fact=state['knowledge'][0]
        sub,files=opinion(state,answers={q['gaps'][0]['id']:'Fresh execution invokes real begin and report in the same context'},
            rationale='The actual producer emits notification before completion; the guard consumes the weaker fact')
        sub['knowledge']=[dict(id=fact['id'],kind='fact',statement='A notification establishes reporting, not completion',
            conditions='Current admitted ticket; report may precede finish',source_ids=['code','doc'],
            changed_premise='Reporting does not establish completion',affected_uses=[q['id'],later['id']])]
        return sub,files
    def reuse(state):
        q=state['investigations'][1]
        fact=state['knowledge'][0]
        assert q['gaps'] and fact['revision']==2
        index=json.loads((e.root/'research.json').read_text())
        assert set(index['knowledge'][0]['last_correction']['recorded_uses'])=={i['id'] for i in state['investigations']}
        return {'rationale':'Reuse the corrected conditional fact for transition analysis',
            'investigations':[dict(id=q['id'],knowledge=[dict(entry_id=fact['id'],revision=2)],
                discriminator='Check that advance retires reported tickets')],
            'interpretations':[dict(investigation_id=q['id'],source_ids=['code'],conclusion='explained',
                rationale='advance clears pending and reported sets and changes the ticket context',
                answers={q['gaps'][0]['id']:'Source clears the weaker reporting fact at transition; it never promised completion'},
                knowledge=[dict(entry_id=fact['id'],revision=2)])]},{}
    e,repo=engine_for(tmp_path,[initial,prefix,correct,reuse,stop])
    (repo/'target.py').write_text(Path('tests/fixtures/research_protocol.py').read_text())
    (repo/'README.md').write_text('Calls are serialized; report may precede finish; allowed requires completion of a current ticket.\n')
    state=e.start(repo)
    assert len(state.experiments)==2, state.current_submission
    assert state.knowledge[0].revision==2 and len(state.knowledge[0].history)==1
    assert state.investigations[1].knowledge[0].revision==2
    assert not open_gaps(state,state.investigations[1].id)
    assert open_gaps(state,state.investigations[0].id)
    assert state.experiments[0].basis.scope.assumptions
    assert not state.experiments[1].basis.scope.assumptions
    assert all(assessment(state,e.root,a,next(c for c in state.checks if c.experiment_id==a.id))['outcome']=='violated' for a in state.experiments)


@pytest.mark.parametrize('protected,expected',[(False,'violated'),(True,'holds')])
def test_same_actual_measurement_distinguishes_bug_and_control(tmp_path,protected,expected):
    e,repo=engine_for(tmp_path,[lambda state:research_case(state,protected),stop])
    (repo/'target.py').write_text(Path('tests/fixtures/research_protocol.py').read_text())
    (repo/'README.md').write_text('report may precede finish; allowed requires completed current work.\n')
    state=e.start(repo)
    assert state.experiments,state.current_submission
    a=state.experiments[0]
    c=next(c for c in state.checks if c.experiment_id==a.id)
    result=assessment(state,e.root,a,c)
    assert result['outcome']==expected
    from consensus_assurance.workflow.observations import compare_events
    assert compare_events([],a.basis.comparisons[0],a.basis.harness.prerequisites)['outcome']=='unknown'
    fabricated=[dict(event='admitted',operation='one',epoch=0),dict(event='result',operation='one',epoch=0,allowed=False,finished=False)]
    if not protected:
        assert compare_events(fabricated,a.basis.comparisons[0],a.basis.harness.prerequisites)['outcome']!=expected


@pytest.mark.parametrize('directed', [False, True])
def test_only_finite_answered_task_can_complete_early(tmp_path, directed):
    def finish(state):
        sub, files = first(state)
        sub['investigations'][0]['disposition'] = 'explained'
        sub['interpretations'] = [dict(investigation_id='@q', source_ids=['code'], conclusion='explained',
                                      rationale='The visible local boundary branch returns zero')]
        sub['stop'] = dict(reason='bounded_completed', rationale='The finite local source question is answered')
        return sub, files

    engine, repo = engine_for(tmp_path, [finish, stop])
    if not directed:
        engine.config.directed_question = None
    state = engine.start(repo)
    if directed:
        assert state.run_stop['reason'] == 'bounded_completed'
        assert state.usage['agent_calls'] == 1
    else:
        assert not state.investigations and not state.interpretations
        assert list((engine.root / 'submissions').glob('*/diagnostics.json'))
        assert state.usage['agent_calls'] == 2


def test_unrelated_knowledge_addition_preserves_results_and_probe_needs_no_requirement(tmp_path):
    def probe(state):
        sub, files = combined(state)
        for key in ('requirement', 'responsibility', 'comparisons', 'anchors'):
            sub['experiment'].pop(key)
        return sub, files

    before = []

    def knowledge(state):
        before.append(state['experiments'])
        return {'rationale': 'Independent sourced understanding', 'knowledge': [dict(
            kind='behavior', statement='The function returns zero at capacity', conditions='value equals limit',
            source_ids=['code'])]}, {}

    engine, repo = engine_for(tmp_path, [probe, knowledge, stop])
    state = engine.start(repo)
    assert [a.model_dump(mode='json') for a in state.experiments] == before[0]
    assert state.knowledge and not state.investigations[0].gaps
    check = next(c for c in state.checks if c.experiment_id)
    result = assessment(state, engine.root, state.experiments[0], check)
    assert result['events'][1]['value'] == 0
    assert result['outcome'] == 'unknown' and not result['confirmed']
