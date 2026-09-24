"""Public native loop with scripted transport and actual isolated Python execution."""
import json
from pathlib import Path
import pytest
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
        return {'available':True,'version':'scripted-native/1','checks':[],'reason':'Explicit transport fixture'}

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        state = json.loads((runner.root/'state.json').read_text())
        value, files = self.steps[self.cursor](state)
        self.cursor += 1
        for name, content in files.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (directory/'submission.json').write_text(value if isinstance(value,str) else json.dumps(value))
        return CheckRun(action='native_agent',cwd=str(directory),snapshot_id=snapshot_id,
            status=ExecutionStatus.COMPLETED,exit_code=0), 'fixture-session', {
            'submission':'submission.json','summary':'Scripted transport; tools execute locally'}


def products():
    basis = dict(source_ids=['code'], expectation_ids=['doc'], binding_ids=['binding'],
        derivation='Return after an actual legal invocation remains bounded', applicability='One legal local call')
    question = dict(question='Does a boundary call return within capacity?',importance='A bad returned value misleads the consumer',
        source_ids=['code','doc'],disposition='ready_for_check',preferred_check='direct_test',
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
            semantic_changes=['Emit actual observed fields'],legality=basis,
            prerequisites=[dict(alias='start',event='admitted',conditions=[dict(field='state.legal',value=True)])]),
        observable_properties=[dict(checker_id='Bounded',kind='event_assertion',trigger=dict(field='event',value='returned'),
            assertion=dict(field='state.in_range',value=True),identity_fields=['operation'],description='Return within capacity')],
        monitors=[dict(id='bound',checker_id='Bounded',event='returned',binding_ids=['binding'],grounding=basis)])
    harness="""import json
from target import step
from helper import legal
print('CA_EVENT '+json.dumps({'event':'admitted','operation':'one','state':{'legal':legal(3,3)}}))
value=step(3,3)
print('CA_EVENT '+json.dumps({'event':'returned','operation':'one','state':{'in_range':0 <= value <= 3}}))
"""
    return obligation, plan, harness


def first(state):
    return products()[0], {}


def check_step(broken=False, revise=False):
    def step(state):
        _, plan, harness = products()
        if broken:
            harness += 'invalid syntax here\n'
        submission=dict(action='revise_check' if revise else 'check',unit_id=state['units'][0]['id'],
            plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},rationale='Repair compilation' if revise else 'Execute the accepted obligation')
        if revise:
            submission['previous_check_id']=state['direct_checks'][-1]['id']
        return submission, {'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(value, limit):\n    return 0 <= value <= limit\n'}
    return step


def review_step(status='no_issue_found',aspect='checker_correspondence'):
    def step(state):
        artifact=state['direct_checks'][-1]
        item=dict(target_id=artifact['id'],aspect=aspect,status=status,source_ids=['code','doc'],
            rationale='Actual source, legality, result and independent bound agree within this local call')
        if status in {'disputed','revision_needed'}:item['counterevidence']=['The current assumption needs a distinct source check']
        return dict(action='review',artifact_id=artifact['id'],review_items=[item],rationale='Review the saved execution'),{}
    return step


def stop(state):
    return {'action':'stop','rationale':'Bounded fixture is complete; no autonomous claim'},{}


def engine_for(tmp_path, steps):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('For 0 <= value <= limit and positive limit, the returned value stays in [0, limit].\n')
    cfg=Config(agent_backend='mock',execution_backend='python',execution_isolation='workspace',
        budget=Budget(agent_calls=len(steps),experiments=4,revisions=4,semantic_reviews=4,total_seconds=90))
    e=Engine(cfg,tmp_path/'run',PythonBackend(),ScriptedAgent(steps),None,'')
    return e,repo
