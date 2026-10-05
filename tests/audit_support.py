"""Public audit loop with scripted transport and actual isolated Python execution."""
import json
from consensus_assurance.core.config import Config, Budget
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.runners.python import PythonBackend


class ScriptedAgent:
    name = 'offline'
    mock = True
    available = True

    def __init__(self, steps):
        self.steps, self.cursor = steps, 0

    def probe(self, runner):
        return {'available':True,'version':'scripted-audit/1','checks':[],'reason':'Explicit transport fixture'}

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        state = json.loads((runner.root/'state.json').read_text())
        step = self.steps[self.cursor]
        self.cursor += 1
        try:
            value, files = step(state)
        except KeyboardInterrupt:
            # The test caller cancels at the transport boundary, as ProcessRunner does.
            return CheckRun(action='agent_turn',cwd=str(directory),snapshot_id=snapshot_id,
                status=ExecutionStatus.CANCELLED,reason='Test caller cancelled the investigation'),session_id,None
        for name, content in files.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (directory/'submission.json').write_text(value if isinstance(value,str) else json.dumps(value))
        return CheckRun(action='agent_turn',cwd=str(directory),snapshot_id=snapshot_id,
            status=ExecutionStatus.COMPLETED,exit_code=0), 'fixture-session', {
            'submission':'submission.json','summary':'Scripted transport; tools execute locally'}


def products():
    basis = dict(source_ids=['code'], expectation_ids=['doc'], binding_ids=['binding'],
        derivation='Return after an actual legal invocation remains bounded', applicability='One legal local call')
    question = dict(question='Does a boundary call return within capacity?',importance='A bad returned value misleads the consumer',
        source_ids=['code','doc'],disposition='ready_for_check',preferred_check='direct_test',
        audit_spec_version=1,activity_classes=['A1'],behavior_ids=['call'],fact_ids=['result'],
        obligation_relation_kind='establishment',contexts=['One legal synchronous invocation'],
        event_paths=['admitted -> called -> returned'],trigger_rationale='Read the actual return and independent bound')
    obligation = dict(action='obligation',question=question,rationale='Check a bounded actual call',
        sources=[dict(id='code',file='target.py',start_line=1,end_line=2,kind='code_observation'),
                 dict(id='doc',file='README.md',start_line=1,end_line=1,kind='document_statement')],
        obligation=dict(id='bounded',kind='obligation',description='Return remains within capacity for legal input',
            source_ids=['code','doc'],scope={'description':'one local legal call','excluded':['distributed consequences']},pending=[],grounding=basis),
        bindings=[dict(id='binding',material_id='code',symbol='step',start_line=1,end_line=2,
            associations=[dict(claim_id='bounded',rationale='The selected actual call implements the return',source_ids=['code'])],
            description='Actual transition',pending=[])])
    plan=dict(description='One legal boundary call',claim_id='bounded',binding_ids=['binding'],
        harness=dict(kind='python',source='',description='Actual target call with independent return observation',
            semantic_changes=['Emit actual observed fields'],
            legality={**basis,'derivation':'Call the bound step function.','applicability':'Legal synchronous input.'},
            prerequisites=[dict(alias='start',event='admitted',conditions=[dict(field='state.legal',value=True)])]),
        observable_properties=[dict(checker_id='Bounded',kind='event_assertion',trigger=dict(field='event',value='returned'),
            assertion=dict(field='state.in_range',value=True),identity_fields=['operation'],description='Return within capacity')],
        monitors=[dict(id='bound',checker_id='Bounded',event='returned',binding_ids=['binding'],grounding={**basis,'derivation':'Compare the observed return to input capacity.',
                'applicability':'Same admitted call.'},admission_alias='start')])
    harness="""import json
from target import step
from helper import legal
print('CA_EVENT '+json.dumps({'event':'admitted','operation':'one','state':{'legal':legal(3,3)}}))
value=step(3,3)
print('CA_EVENT '+json.dumps({'event':'returned','operation':'one','state':{'in_range':0 <= value <= 3}}))
"""
    return obligation, plan, harness


def first(state):
    sub=products()[0]
    sub['map_path']='map.json'
    return sub, {'map.json':json.dumps(partial_map())}


def partial_map():
    return dict(version=1,target_profile=dict(system_boundary='One local operation',source_ids=['code']),
        activities=[dict(class_id='A1',applicability='applicable',purpose='Produce a local result',
            realization_summary='A synchronous call returns a bounded value',source_ids=['code'])],
        behaviors=[dict(id='call',primary_activity='A1',execution_owner='caller',protocol_context='one request',
            trigger='invoke',produces_fact_ids=['result'],source_ids=['code'],existing_protections=['Capacity branch'])],
        facts=[dict(id='result',meaning='The invocation delivered a return value',identity={'operation':'one'},
            validity_context='one completion',representation=['return'],durability='volatile',recovery='none',
            unknowns=['Consumer outside boundary'],source_ids=['code'])])


def feedback(state, **overrides):
    refs=[s['operation_id'] for s in state.get('selections',[]) if s['action'] in {'pause','explained'}]
    refs += [r['id'] for r in state['semantic_reviews']]
    return dict(ref_ids=list(dict.fromkeys(refs+['code','doc'])),answered='The local return discriminator is bounded by this invocation',
        remaining=['External consumer invocation ordering is not supplied'],understanding='unchanged',
        rationale='The source map already expresses the bounded call; no structural generalization from a test',**overrides)


def check_step(broken=False, revise=False):
    def step(state):
        _, plan, harness = products()
        if broken:
            harness += 'invalid syntax here\n'
        submission=dict(action='revise_check' if revise else 'check',unit_id=state['units'][0]['id'],
            plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},rationale='Repair compilation' if revise else 'Execute the accepted obligation')
        if revise:
            submission['previous_check_id']=state['direct_checks'][-1]['id']
        if state.get('semantic_reviews'):submission['feedback']=feedback(state)
        return submission, {'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(value, limit):\n    return 0 <= value <= limit\n'}
    return step


def review_step(status='no_issue_found',aspect='checker_correspondence'):
    def step(state):
        artifact=state['direct_checks'][-1]
        item=dict(target_id=artifact['id'],aspect=aspect,status=status,source_ids=['code','doc'],
            rationale='Actual source, legality, result and independent bound agree within this local call')
        if status in {'disputed','revision_needed'}:item['counterevidence']=['The current assumption needs a distinct source check']
        if status=='revision_needed':item['challenged_components']=['oracle']
        return dict(action='review',artifact_id=artifact['id'],review_items=[item],rationale='Review the saved execution'),{}
    return step


def stop(state):
    raise KeyboardInterrupt('Explicit test caller cancellation')


def engine_for(tmp_path, steps):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('For 0 <= value <= limit and positive limit, the returned value stays in [0, limit].\n')
    cfg=Config(agent_backend='mock',execution_backend='python',execution_isolation='workspace',
        directed_question='Check the bounded local return contract of the synthetic target',
        budget=Budget(agent_calls=len(steps),experiments=4,revisions=4,semantic_reviews=4,total_seconds=90))
    e=Engine(cfg,tmp_path/'run',PythonBackend(),ScriptedAgent(steps),'')
    return e,repo


def completion_target(variant):
    """Offline controls; export only the selected source and its caller contract."""
    assert variant in {'overlap', 'guarded', 'ordered'}
    predicate = 'ticket in completed' if variant == 'guarded' else 'ticket in reported'
    contract = ('report may precede finish.' if variant != 'ordered' else
        'The caller must finish a ticket before reporting it.')
    return {'README.md':
        'Calls are serialized. begin returns a unique live ticket; advance retires all old tickets. '
        'finish completes work; report records a caller notification. ' + contract +
        ' For compliant calls, allowed may be true only after work completed for the current ticket.\n',
        'target.py': '''generation = 0
pending = set()
completed = set()
reported = set()


def begin(name):
    ticket = (generation, name)
    if ticket in pending:
        raise ValueError("Duplicate live request")
    pending.add(ticket)
    return ticket


def advance():
    global generation
    generation += 1
    pending.clear()
    completed.clear()
    reported.clear()


def finish(ticket):
    if ticket not in pending:
        return False
    completed.add(ticket)
    reported.add(ticket)
    return True


def report(ticket):
    if ticket not in pending:
        return False
    reported.add(ticket)
    return True


def allowed(ticket):
    return ticket in pending and ''' + predicate + '\n'}


def diagnostics(engine):
    return [json.loads(p.read_text()) for p in (engine.root/'submissions').glob('*/diagnostics.json')]


def question_step(state):
    sub,files=first(state)
    sub.update(action='continue',obligation=None,bindings=[])
    sub['question'].update(disposition='needs_specific_evidence',unknowns=['Consumer unexamined'])
    return sub,files


def next_question(state):
    sub=products()[0]
    sub.update(action='continue',obligation=None,bindings=[],sources=[])
    sub['question'].update(contexts=['Another sourced invocation'],
        disposition='needs_specific_evidence',unknowns=['Inspect the other invocation boundary'])
    return sub,{}


def local_stop(reason='bounded_completed', scope='candidate'):
    def step(state):
        candidate=state['question_candidates'][-1]
        return dict(action='stop',scope=scope,reason=reason,ref_ids=[candidate['id']],
            rationale='The scoped discriminator is disposed; compare other sourced directions',
            resume_conditions=[] if reason=='bounded_completed' else ['Acquire the missing producer observation'],
            feedback=feedback(state)),{}
    return step


def instance_products():
    source = '''def create(eligible):
    return dict(eligible=set(eligible), context=None, support={}, decision=None)

def change(instance, context):
    if context is None or context == instance['context']:
        return False
    instance['context'], instance['support'] = context, {}
    return True

def support(instance, context, member, value):
    if context != instance['context'] or member not in instance['eligible']:
        return False
    instance['support'][member] = value
    if set(instance['support']) != instance['eligible'] or set(instance['support'].values()) != {value}:
        return False
    if instance['decision'] is None:
        instance['decision'] = value
    return instance['decision'] == value

def read(instance):
    return instance['decision']
'''
    spec=partial_map()
    spec['target_profile']=dict(system_boundary='Synthetic per-instance support; callers and crashes outside',
        protocol_contexts=['Independent instance context'],source_ids=['code'])
    spec['activities']=[dict(class_id=a,applicability='applicable',purpose=p,realization_summary=r,source_ids=['code'])
        for a,p,r in [('A1','Form an instance decision','Collect matching support from configured identities'),
            ('A2','Change per-instance context','Discard pending support; preserve the decision'),
            ('A4','Configure eligible identities','The caller supplies a set at instance creation'),
            ('A5','Consume the decision','read exposes the stored decision')]]
    spec['behaviors']=[dict(id=id,primary_activity=a,execution_owner='Instance caller',protocol_context='One instance',
        trigger=trigger,produces_fact_ids=produces,consumes_fact_ids=consumes,source_ids=['code'])
        for id,a,trigger,produces,consumes in [('call','A1','support call',['result'],['context']),
            ('change','A2','change call',['context'],[]),('init','A4','create call',[],[]),
            ('read','A5','read call',[],['result'])]]
    spec['facts']=[dict(id=id,meaning=meaning,identity={'instance':'Selected object'},validity_context=context,
        representation=[representation],durability='Volatile',recovery='Not implemented in this source',
        source_ids=['code'],unknowns=unknowns)
        for id,meaning,context,representation,unknowns in [
            ('result','First decision established by all configured matching support','Preserved across change','decision',[]),
            ('context','Active per-instance context after change','Until next change','context',['Caller authorization is outside the source'])]]
    spec['surfaces']=[dict(entry_point='read',disposition='deferred',source_ids=['code'],
        reason='Caller timing and completion contract need investigation; preserve this early lead')]
    def path(text,bs,fs):return dict(explanation=text,behavior_ids=bs,fact_ids=fs,source_ids=['code'])
    spec['core_overview']=dict(status='usable',rationale='The finite in-memory paths and their connection are explained; caller policy remains open',
        formation=path('support rejects stale or ineligible input, records one value per member, requires all eligible members to agree, preserves the first decision; read exposes it',['call','init','read'],['result','context']),
        context=path('create leaves context unset; change accepts a distinct non-null context, resets support, preserves decision and rejects redundant change',['init','change'],['context']),
        connection=path('support requires the current context; change invalidates pending support while the established decision survives and constrains later return',['call','change'],['result','context']),
        core_gaps=[],open_details=['Retry policy of unavailable external callers'])
    return source,spec
