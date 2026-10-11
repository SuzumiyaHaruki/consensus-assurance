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
    def initial(state):
        sub,files=research_case(state,supplied=True)
        sub['knowledge'][0].update(kind='behavior',statement='Both guard branches grant after report')
        sub['knowledge'].extend(dict(kind='behavior',statement=statement,conditions='Serialized calls',source_ids=['code'])
            for statement in ('begin allocates a ticket','finish records a pending ticket','advance clears the pending set'))
        sub['experiment']['knowledge']=[dict(entry_id='@fact',revision=1)]
        sub['investigations'][1]['knowledge']=[]
        return sub,files
    def prefix(state):
        sub,files=research_case(state)
        sub['experiment']['knowledge']=[dict(entry_id=state['knowledge'][0]['id'],revision=1)]
        return sub,files
    def branch_control(state):
        sub,files=research_case(state,protected=True)
        sub['experiment']['revision_reason']='Observe the legitimate protected guard branch using the same actual producer prefix'
        sub['interpretations']=opinion(state,knowledge=[dict(entry_id=state['knowledge'][0]['id'],revision=1)],
            rationale='The reporting branch grants before finish; whether this generalizes to the other branch remains to be checked')[0]['interpretations']
        return sub,files
    def correct(state):
        q,later=state['investigations']
        fact=state['knowledge'][0]
        check=next(c for c in state['checks'] if c.get('experiment_id')==state['experiments'][-1]['id'])
        sub,files=opinion(state,conclusion='holds',knowledge=[dict(entry_id=fact['id'],revision=2)],
            answers={q['gaps'][0]['id']:'Fresh executions invoke real begin and report in the same context'},
            rationale='The protected branch requires finish; the earlier general statement about both branches was inaccurate')
        sub['knowledge']=[dict(id=fact['id'],kind='behavior',
            statement='The reporting branch grants after report; the protected branch requires finish',
            conditions='Current admitted ticket; report may precede finish',source_ids=['code','doc'],
            executions={check['id']:[1]},changed_premise='Grant after report applies only to the reporting branch',
            affected_uses=[q['id'],state['experiments'][1]['id'],state['interpretations'][0]['id']])]
        corrected.append(sub['knowledge'][0])
        return sub,files
    corrected=[]
    def duplicate(state):
        return {'rationale':'Repeat the same effective correction','knowledge':corrected},{}
    def global_choice(state):
        assert state['current_submission']['no_change']
        from consensus_assurance.workflow.research import operation_summary
        summary=operation_summary(e.state,e.root)
        assert 'any valuable A1/A2' in summary['next'] and summary['reselection']['target']['repo']==str(repo)
        index=json.loads((e.root/'research.json').read_text())
        entry=index['reselection']['recent_knowledge'][-1]
        assert entry['revision']==2 and entry['last_correction']['affected_uses']==corrected[0]['affected_uses']
        assert entry['statement']==corrected[0]['statement'] and entry['executions']
        q=state['investigations'][1]
        assert not q['gaps'] and not q['knowledge']
        return {'rationale':'Select the independent authority question, not another guard variant',
            'investigations':[dict(id=q['id'],disposition='explained')],
            'interpretations':[dict(investigation_id=q['id'],source_ids=['code'],conclusion='explained',
                rationale='advance changes epoch and clears pending tickets, protecting against old-ticket reuse')]},{}
    def local_lead(state):
        return {'rationale':'A separate local completion responsibility becomes worth tracing',
            'investigations':[dict(question='Can a reported ticket be explicitly finished before authority changes?',
                source_ids=['code'],knowledge=[dict(entry_id=state['knowledge'][0]['id'],revision=2)],
                discriminator='Trace the actual finish producer, independent of whether report alone grants')]},{}
    e,repo=engine_for(tmp_path,[initial,prefix,branch_control,correct,duplicate,global_choice,local_lead,stop])
    e.config.directed_question=None
    (repo/'target.py').write_text(Path('tests/fixtures/research_protocol.py').read_text())
    (repo/'README.md').write_text('Calls are serialized; report may precede finish; allowed requires completion of a current ticket.\n')
    state=e.start(repo)
    assert len(state.experiments)==3, state.current_submission
    assert state.knowledge[0].revision==2 and len(state.knowledge[0].history)==1
    assert all(k.revision==1 and not k.history for k in state.knowledge[1:])
    assert not open_gaps(state,state.investigations[1].id)
    assert open_gaps(state,state.investigations[0].id)
    assert state.investigations[2].knowledge[0].revision==2
    assert all(q.parent_id is None for q in state.investigations)
    assert state.knowledge[0].history[0]['statement']=='Both guard branches grant after report'
    assert state.experiments[1].basis.knowledge[0].revision==1 and state.interpretations[0].knowledge[0].revision==1
    assert len(state.interpretations)==3 and state.agent_session_id=='fixture-session'
    assert state.experiments[0].basis.scope.assumptions
    assert not state.experiments[1].basis.scope.assumptions
    assert [assessment(state,e.root,a,next(c for c in state.checks if c.experiment_id==a.id))['outcome'] for a in state.experiments]==['violated','violated','holds']


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


def test_evidence_enrichment_preserves_used_premise_and_exploratory_results(tmp_path):
    def probe(state):
        sub, files = combined(state)
        for key in ('requirement', 'responsibility', 'comparisons', 'anchors'):
            sub['experiment'].pop(key)
        if state['experiments']:
            assert state['experiments'] == before[0] and not state['investigations'][0]['gaps']
            sub.pop('investigations')
            sub.pop('sources')
            sub['experiment'].update(investigation_id=state['investigations'][0]['id'],
                previous_id=state['experiments'][0]['id'], revision_reason='Sample another legal capacity input',
                knowledge=[dict(entry_id=state['knowledge'][0]['id'], revision=1)])
            files['check.py'] = files['check.py'].replace('3', '4')
        return sub, files

    before = []

    def knowledge(state):
        before.append(state['experiments'])
        return {'rationale': 'Retain the sourced premise with its actual samples', 'knowledge': [dict(
            ref='@behavior', id=state['knowledge'][0]['id'] if state['knowledge'] else None,
            kind='behavior', statement='The function returns zero at capacity', conditions='value equals limit',
            source_ids=['code'], executions={c['id']:[1] for c in state['checks'] if c.get('experiment_id')})],
            'investigations':[dict(id=state['investigations'][0]['id'],
                knowledge=[dict(entry_id='@behavior',revision=1)])]}, {}

    engine, repo = engine_for(tmp_path, [probe, knowledge, probe, knowledge, stop])
    state = engine.start(repo)
    assert [a.model_dump(mode='json') for a in state.experiments] == before[-1]
    entry = state.knowledge[0]
    assert entry.revision == 2 and len(entry.history) == 1 and len(entry.executions) == 2
    history = entry.history[0]
    assert (entry.statement, entry.conditions) == (history['statement'], history['conditions'])
    assert not history['correction'] and not history['affected_uses'] and not state.investigations[0].gaps
    assert set(history['recorded_uses']) == {state.investigations[0].id, state.experiments[1].id}
    assert len(history['executions']) == 1 and history['executions'].items() <= entry.executions.items()
    assert state.investigations[0].knowledge[0].revision == state.experiments[1].basis.knowledge[0].revision == 1
    for fixed in state.experiments:
        check = next(c for c in state.checks if c.experiment_id == fixed.id)
        result = assessment(state, engine.root, fixed, check)
        assert result['events'][1]['value'] == 0
        assert result['outcome'] == 'unknown' and not result['confirmed']
    index = json.loads((engine.root/'research.json').read_text())['reselection']['recent_knowledge'][0]
    assert index['revision'] == 2 and set(index['executions']) == set(entry.executions)
    assert index['last_correction']['correction'] == '' and index['last_correction']['recorded_uses'] == history['recorded_uses']
