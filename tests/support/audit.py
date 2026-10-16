"""Scripted delivery through the production audit loop; target processes execute locally."""
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


def stop(state):
    raise KeyboardInterrupt('Explicit test caller cancellation')


def engine_for(tmp_path, steps):
    repo=tmp_path/'repo'
    repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('For 0 <= value <= limit and positive limit, the returned value stays in [0, limit].\n')
    cfg=Config(agent_backend='mock',execution_backend='python',execution_isolation='workspace',
        directed_question='Check the bounded local return contract of the synthetic target',
        budget=Budget(agent_calls=len(steps),experiments=4,total_seconds=90))
    e=Engine(cfg,tmp_path/'run',PythonBackend(),ScriptedAgent(steps),'')
    return e,repo


def cargo_engine(tmp_path, rust_workspace, steps=(), seed_cache=None):
    import shutil
    from consensus_assurance.core.config import TargetConfig
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    engine,repo=engine_for(tmp_path,steps)
    shutil.copytree(rust_workspace,repo,dirs_exist_ok=True)
    engine.config.target=TargetConfig(execution_package='sample')
    engine.config.execution_backend='cargo'
    engine.config.execution_isolation='bwrap'
    engine.config.cargo_seed_cache_dir=str(seed_cache) if seed_cache else None
    engine.implementation=CargoBackend(engine.config.target,seed_cache_dir=seed_cache)
    return engine,repo


def first(state):
    return {'rationale':'Trace the actual local return',
        'sources':[dict(id='code',file='target.py',start_line=1,end_line=2,kind='code_observation'),
                   dict(id='doc',file='README.md',start_line=1,end_line=1,kind='document_statement')],
        'investigations':[{'ref':'@q','question':'Does the actual local return remain bounded?',
            'source_ids':['code','doc'],'hypothesis':'The boundary may wrap','discriminator':'Observe the return'}]}, {}


def experiment(owner='@q', *, source=None):
    harness = source or '''import json
from target import step
print('CA_EVENT '+json.dumps(dict(event='admitted',operation='one',value=3,limit=3)))
value = step(3,3)
print('CA_EVENT '+json.dumps(dict(event='returned',operation='one',value=value)))
'''
    request = dict(investigation_id=owner, harness_path='check.py', source_ids=['code','doc'],
        anchors=[dict(material_id='code',symbol='step',start_line=1,end_line=2)],
        scope={'description':'One legal synchronous local call'}, prefix='Call the actual step with legal capacity input.',
        requirement='The return equals the admitted input when capacity has been reached.',
        responsibility='Use the local boundary contract as the fixture expected result, not an inferred consensus obligation.',
        prerequisites=[dict(alias='start',event='admitted')],
        comparisons=[dict(event='returned',identity_fields=['operation'],admission_alias='start',
                          assertion=dict(field='value',reference='start.value'))])
    return request, {'check.py':harness}


def combined(state):
    sub, files = first(state)
    sub['experiment'], generated = experiment()
    files.update(generated)
    return sub, files


def opinion(state, **changes):
    a=state['experiments'][-1]
    c=next(c for c in reversed(state['checks']) if c.get('experiment_id')==a['id'])
    value=dict(investigation_id=a['investigation_id'],experiment_id=a['id'],source_ids=['code','doc'],
               executions={c['id']:[1]},conclusion='violated',defect_claim=None,rationale='Compare the actual return with independent admitted input')
    value.update(changes)
    return {'rationale':'Interpret the saved receipt','interpretations':[value]}, {}
