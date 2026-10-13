from consensus_assurance.core.submissions import SourceRange
"""Codex transport protocol, local permission preflight and source boundaries."""
import json
from pathlib import Path
import pytest
from consensus_assurance.adapters.agents.backend import CodexAgent, failure_reason
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Analysis
from consensus_assurance.workflow.audit import prepare_agent_source, source_materials
from consensus_assurance.adapters.storage.snapshot import capture


@pytest.mark.parametrize('terminal,exit_code,status,lost',[
    ({'type':'turn.failed','error':{'message':'This content was flagged for possible cybersecurity risk.'}},1,ExecutionStatus.ERROR,False),
    ({'type':'turn.failed','error':{'message':'Transport stopped'}},0,ExecutionStatus.ERROR,False),
    ({'type':'error','message':'HTTP 401 Unauthorized'},1,ExecutionStatus.LOGIN_REQUIRED,False),
    ({'type':'turn.failed','error':{'code':'insufficient_quota','message':'Account exhausted'}},1,ExecutionStatus.QUOTA_EXHAUSTED,False),
    ({'type':'error','message':'thread not found'},1,ExecutionStatus.ERROR,True),
    ({'type':'turn.failed','error':{'message':'thread not found; request timed out; permission denied'}},1,ExecutionStatus.ERROR,False),
    ({'type':'turn.failed','error':{'message':'thread not found; insufficient_quota'}},1,ExecutionStatus.QUOTA_EXHAUSTED,False),
    (None,1,ExecutionStatus.ERROR,False)])
def test_audit_failure_uses_transport_diagnostics_not_tool_output(tmp_path,terminal,exit_code,status,lost):
    events=[{'type':'thread.started','thread_id':'saved'},
        {'type':'item.completed','item':{'id':'tool','type':'command_execution',
            'aggregated_output':'401 case request: login required; quota exceeded; request timed out; thread not found'}}]
    if terminal: events.append(terminal)
    log=tmp_path/'events.jsonl';log.write_text('\n'.join(json.dumps(e) for e in events))
    check=CheckRun(action='agent_turn',cwd=str(tmp_path),snapshot_id='fixture',
        status=ExecutionStatus.COMPLETED,exit_code=exit_code,stdout=str(log))
    check,session,result=CodexAgent().decode(check,tmp_path/'absent.json','saved')
    assert check.status==status and session=='saved' and result is None
    assert bool(check.parameters.get('agent_session_unavailable'))==lost
    assert not check.parameters['agent_diagnostic']['transport_failure']
    if terminal:
        error=terminal.get('error') or terminal
        assert error['message'] in check.reason
    else:
        assert check.reason=='Agent execution blocked; inspect raw logs'
    assert 'case request' not in check.reason


@pytest.mark.parametrize('extra,completed,retry',[
    (None,False,True), ('This content was flagged for possible cybersecurity risk.',False,False),
    ('Permission denied; request timed out',False,False), ('HTTP 403: error sending request',False,False),
    ('HTTP/1.1 403: error sending request',False,False), ('rate_limit_exceeded: stream disconnected',False,False),
    ('thread not found; This content was flagged for possible cybersecurity risk.',False,False),
    ('insufficient_quota; request timed out',False,False), ('Unclassified failure',False,False),
    (None,True,True)])
def test_transport_diagnostic_keeps_mixed_restrictions_and_completed_reconnects(tmp_path,extra,completed,retry):
    events=[{'type':'thread.started','thread_id':'saved'}, {'type':'error','message':'stream disconnected: request timed out'}]
    if extra:events.append({'type':'turn.failed','error':{'message':extra}})
    if completed:events.append({'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':3}})
    log=tmp_path/'events.jsonl';log.write_text('\n'.join(map(json.dumps,events)))
    response=tmp_path/'response.json';response.write_text(json.dumps({'submission':'input.json','summary':'Complete'}))
    check=CheckRun(action='agent_turn',cwd=str(tmp_path),snapshot_id='fixture',stdout=str(log),
        status=ExecutionStatus.COMPLETED if completed else ExecutionStatus.TIMEOUT,exit_code=0 if completed else -9)
    check,session,result=CodexAgent().decode(check,response,'saved')
    assert check.parameters['agent_diagnostic']['transport_failure']==retry
    assert session=='saved' and not check.parameters.get('agent_session_unavailable')
    if completed:
        assert result['submission']=='input.json' and check.status==ExecutionStatus.COMPLETED
        assert check.parameters['agent_usage']['input_tokens']==12
    else:assert result is None and check.status==ExecutionStatus.TIMEOUT


@pytest.mark.parametrize('boundary',[
    'turn','turn_crash','completed_turn','total','action','unlabelled','cancelled','no_session',
    'refusal','permission','session_lost','empty_error','calls','time'])
def test_turn_deadline_continues_only_saved_session_with_capacity(tmp_path,boundary):
    from audit_support import ScriptedAgent,engine_for,first
    engine,repo=engine_for(tmp_path,[first,first])
    resumed=boundary in {'turn','turn_crash'}
    if boundary=='calls':engine.config.budget.agent_calls=1
    class InterruptedAgent(ScriptedAgent):
        def investigate(self,runner,prompt,directory,snapshot_id,timeout,session_id=None):
            if self.cursor:
                assert resumed and session_id=='saved'
                assert not engine.state.investigations and not engine.state.materials
                assert engine.state.usage['agent_calls']==2
                assert 'interrupted_turn' in prompt and self.check.id in prompt and self.check.stdout in prompt
                assert json.loads(Path(self.check.stdout).with_name('check.json').read_text())['status']=='timeout'
                check,_,result=super().investigate(runner,prompt,directory,snapshot_id,timeout,session_id)
                return check,session_id,result
            self.cursor+=1
            assert session_id is None
            draft,_=first(engine.state.model_dump(mode='json'))
            draft['investigations'][0]['question']='Incomplete draft must not be accepted'
            (directory/'unfinished.json').write_text(json.dumps(draft))
            response=runner.root/'actions'/runner.active_action_id/'agent-response.json'
            response.write_text(json.dumps({'submission':'unfinished.json','summary':'Valid-looking interrupted output'}))
            events=[] if boundary=='no_session' else [{'type':'thread.started','thread_id':'saved'}]
            events.append({'type':'item.completed','item':{'id':'tool','type':'command_execution',
                'aggregated_output':'Fixture case: permission denied; thread not found'}})
            errors={'refusal':'This content was flagged for possible cybersecurity risk.',
                'permission':'Permission denied; request timed out','session_lost':'thread not found','empty_error':''}
            if boundary in errors:events.append({'type':'turn.failed','error':{'message':errors[boundary]}})
            if boundary=='completed_turn':events.append({'type':'turn.completed'})
            self.check=CheckRun(action='agent_turn',cwd=str(directory),snapshot_id=snapshot_id,
                pending_action_id=runner.active_action_id,exit_code=-9,
                status=ExecutionStatus.CANCELLED if boundary=='cancelled' else ExecutionStatus.TIMEOUT,
                reason='Fixture interrupted at '+boundary,
                parameters={} if boundary=='unlabelled' else {'timeout_limit':
                    {'total':'total_seconds','action':'action_timeout'}.get(boundary,'agent_turn_timeout')})
            log=runner.root/'logs'/self.check.id/'stdout.log';log.parent.mkdir(parents=True)
            self.raw='\n'.join(map(json.dumps,events));log.write_text(self.raw)
            self.check.stdout=str(log)
            if boundary=='time':engine.budget.previous=engine.config.budget.total_seconds
            return CodexAgent().decode(self.check,response,session_id)
    engine.agent=InterruptedAgent([first,first])
    if boundary=='turn_crash':
        checkpoint=engine.checkpoint
        def interrupt_after_result(event):
            checkpoint(event)
            if event=='action_result_saved' and engine.state.usage['agent_calls']==2:
                raise KeyboardInterrupt('Interrupt before receiving the completed continuation')
        engine.checkpoint=interrupt_after_result
        with pytest.raises(KeyboardInterrupt):engine.start(repo)
        assert not engine.state.investigations and len(engine.state.agent_turns)==1
        engine.checkpoint=checkpoint
        state=engine.resume()
    else:state=engine.start(repo)
    assert engine.agent.cursor==state.usage['agent_calls']==(2 if resumed else 1)
    assert len(state.agent_turns)==(2 if resumed else 1)
    assert len(state.investigations)==int(resumed) and not state.experiments
    assert not state.usage.get('experiments',0)
    assert Path(engine.agent.check.stdout).read_text()==engine.agent.raw
    assert not (engine.root/'submissions'/engine.agent.check.id).exists()
    assert (engine.root/'draft/unfinished.json').is_file()
    if resumed:
        assert state.agent_session_id=='saved' and 'agent_calls budget exhausted' in state.stop_reason
        actions=[json.loads(p.read_text()) for p in (engine.root/'actions').glob('*/input.json')]
        assert sorted(a['turn'] for a in actions)==[0,1]
        assert next(a for a in actions if a['turn']==1)['session_id']=='saved'
        assert state.investigations[0].question=='Does the actual local return remain bounded?'


def test_audit_failure_reason_preserves_schema_diagnostic_and_redacts_secrets():
    error='ERROR: '+json.dumps({'error':{'code':'invalid_json_schema','message':'Unsupported schema'}})
    assert failure_reason(error)=='Agent output schema rejected (invalid_json_schema): Unsupported schema'
    reason=failure_reason('Transport failed: api_key=fixture-secret '+('x'*1200))
    assert 'fixture-secret' not in reason and '[REDACTED]' in reason and len(reason)<1100


@pytest.mark.parametrize('final',[None, '{"submission":"draft.json","summary":"Done"}\nFinished',
    '{"submission":"draft.json","summary":12}'])
def test_invalid_final_response_remains_a_repairable_format_error(tmp_path,final):
    from audit_support import engine_for, first
    from consensus_assurance.workflow.audit import receive, accept_received
    engine,repo=engine_for(tmp_path,[])
    state=engine.start(repo,plan_only=True)
    draft=engine.root/'draft';draft.mkdir()
    submission,_=first(state.model_dump(mode='json'))
    (draft/'draft.json').write_text(json.dumps(submission))
    response=engine.root/'response.json'
    if final is not None:response.write_text(final)
    log=engine.root/'agent-events.jsonl'
    # Earlier valid-looking text must not replace the actual final response.
    log.write_text('\n'.join(map(json.dumps,[{'type':'thread.started','thread_id':'saved'},
        {'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'submission':'draft.json','summary':'Earlier'})}},
        {'type':'turn.completed'}])))
    check=CheckRun(action='agent_turn',cwd=str(draft),snapshot_id=state.snapshot.id,
        status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
    check,session,result=CodexAgent().decode(check,response,'saved')
    receive(engine,[check.model_dump(mode='json'),session,result])
    archive=engine.root/'submissions'/check.id
    retained=json.loads((archive/'diagnostics.json').read_text())
    assert not accept_received(engine)
    assert state.current_submission['phase']=='rejected'
    assert state.current_submission['rejected']==retained
    assert retained['raw_path']==str(response)
    assert retained['diagnostics'][0]['category']=='format'
    assert 'without surrounding prose' in retained['errors'][0]
    assert 'Invalid submitted input path' not in str(retained)
    assert not state.investigations and state.agent_session_id=='saved'
    # A corrected final response can submit the existing draft in the same session.
    response=engine.root/'repaired-response.json'
    response.write_text(json.dumps({'submission':'draft.json','summary':'Corrected final response'}))
    repaired=CheckRun(action='agent_turn',cwd=str(draft),snapshot_id=state.snapshot.id,
        status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
    repaired,session,result=CodexAgent().decode(repaired,response,session)
    receive(engine,[repaired.model_dump(mode='json'),session,result])
    assert accept_received(engine) and len(state.investigations)==1


@pytest.mark.parametrize('session_id',[None,'exact-session'])
@pytest.mark.parametrize('custom',[False,True])
def test_new_session_or_exact_resume_counts_unique_completed_tool_items(tmp_path,monkeypatch,session_id,custom):
    from consensus_assurance.core.config import CodexProvider
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    monkeypatch.setenv('PROVIDER_TICKET','canary-client-only')
    from datetime import datetime
    from consensus_assurance.adapters.runners.process import ProcessRunner
    clock=[100.0];calls=[]
    monkeypatch.setattr('time.monotonic',lambda:clock[0])
    monkeypatch.setattr('os.killpg',lambda *a:None)
    class Process:
        pid=123;returncode=0
        def __init__(self,command,**kwargs):
            calls.append(command)
            assert (kwargs['env'] is not None)==custom
            if custom:assert kwargs['env']['PROVIDER_TICKET']=='canary-client-only'
        def communicate(self,stdin,timeout):
            context=json.loads(stdin.split('Current turn time allocation (controller record):\n')[1])
            record=json.loads(Path(context['check_record']).read_text())
            assert context['action_id']=='operation' and context['check_id']==record['id']
            assert context['generated_at']==record['started_at']
            assert timeout==context['timeout_seconds']==record['parameters']['timeout_seconds']==(80 if session_id else 900)
            assert context['timeout_limit']==('total_seconds' if session_id else 'agent_turn_timeout')
            assert (datetime.fromisoformat(context['estimated_deadline_utc'])-datetime.fromisoformat(context['generated_at'])).total_seconds()==timeout
            meaning=context['meaning']
            assert 'allocated at generated_at, not a live countdown' in meaning
            assert 'timeout_limit names the limiting budget, not exhaustion' in meaning
            assert 'positive total_seconds allocation still permits useful research within that interval' in meaning
            assert 'Expiry needs no closing submission' in meaning
            assert 'saved run checkpoints' in meaning and 'estimate' in meaning and 'monotonic clock' in meaning
            events=[{'type':'thread.started','thread_id':'exact-session'},
                {'type':'item.started','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.updated','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'answer','type':'agent_message'}},
                {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
            command=calls[-1]
            response=Path(command[command.index('--output-last-message')+1]);response.write_text(json.dumps({'submission':'submission.json','summary':'Done'}))
            return '\n'.join(json.dumps(e) for e in events),''
    monkeypatch.setattr('subprocess.Popen',Process)
    provider=CodexProvider(id='deepseek',base_url='https://api.deepseek.com',env_key='PROVIDER_TICKET') if custom else None
    runner=ProcessRunner(tmp_path);runner.active_action_id='operation';runner.deadline=clock[0]+(100 if session_id else 2000)
    agent=CodexAgent('low','deepseek-flash' if custom else 'gpt-6-astra',provider);agent.available=True;agent.version='fixture-cli'
    agent.sandbox_command=lambda root:['codex']
    def permission(*args):
        clock[0]+=20
        return True,[]
    agent.permission_probe=permission
    agent.prepare(runner,tmp_path/'draft','snapshot')
    check,session,result=agent.investigate(runner,'Investigate',tmp_path/'draft','snapshot',900,session_id)
    # Replaying the same completed action must not recalculate timing or launch another turn.
    before={p:p.read_bytes() for p in tmp_path.glob('logs/*/check.json')}
    monkeypatch.setattr('time.monotonic',lambda:pytest.fail('Completed receipt must precede allocation'))
    replay=runner.run(check.command,tmp_path/'draft','agent_turn','snapshot',900,stdin='Must not be sent')
    assert replay.id==check.id and replay.started_at==check.started_at and replay.ended_at==check.ended_at
    assert replay.parameters['timeout_seconds']==check.parameters['timeout_seconds']
    assert len(calls)==1 and all(p.read_bytes()==raw for p,raw in before.items())
    assert session=='exact-session' and result['submission']=='submission.json'
    assert check.command[:2]==['codex','exec'] and ('resume' in check.command)==bool(session_id)
    assert not {'--ignore-rules','--ephemeral','--last','fork'} & set(check.command)
    assert '--ignore-user-config' in check.command
    assert {'memories.use_memories=false','memories.generate_memories=false'} <= set(check.command)
    assert check.parameters['agent_tool_events']==1 and check.parameters['agent_usage']['input_tokens']==10
    assert ('exact-session' in check.command)==bool(session_id) and 'model_reasoning_effort="low"' in check.command
    assert check.command[check.command.index('-m')+1]==agent.model
    assert check.parameters['codex_provider']==(provider.model_dump(mode='json') if custom else None)
    if custom:
        try:import tomllib
        except ModuleNotFoundError:import tomli as tomllib
        overrides=tomllib.loads('\n'.join(check.command[i+1] for i,arg in enumerate(check.command) if arg=='-c'))
        assert overrides['model_provider']=='deepseek'
        assert overrides['model_providers']['deepseek']==dict(name='deepseek',base_url='https://api.deepseek.com',
            env_key='PROVIDER_TICKET',wire_api='responses',requires_openai_auth=False,supports_websockets=False)
        assert overrides['shell_environment_policy']['filters']=={'PROVIDER_TICKET':'exclude'}
        assert 'PROVIDER_TICKET' not in overrides['shell_environment_policy']['set']
    else:assert not any('model_provider=' in arg or 'model_providers.' in arg for arg in check.command)
    assert 'canary-client-only' not in json.dumps(check.model_dump(mode='json'))


def test_probe_bootstrap_crash_does_not_prove_denial(tmp_path,monkeypatch):
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    source=tmp_path/'agent-source';source.mkdir();(source/'test.py').write_text('safe')
    draft=tmp_path/'draft';draft.mkdir()
    class Runner:
        root=tmp_path
        def run(self,*args,**kwargs):
            return CheckRun(action='codex_permission_probe',cwd=str(draft),snapshot_id='s',status=ExecutionStatus.COMPLETED,exit_code=1)
    agent=CodexAgent();ok,checks=agent.prepare(Runner(),draft,'s')
    assert not ok and checks[0].parameters['permission_result']=='inconclusive_or_unsafe'
    with pytest.raises(RuntimeError,match='before reserving'):
        agent.available=True
        agent.investigate(Runner(),'source',draft,'s',1)


def test_effective_profile_exposes_results_and_retains_root_network_boundary(tmp_path,monkeypatch):
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    monkeypatch.setenv('TMPDIR',str(tmp_path/'host-tmp'))
    options='\n'.join(CodexAgent().permission_options(tmp_path,tmp_path/'draft'))
    for path in ('agent-source','submissions','logs','fixed-experiments','actions','state.json','research.json',
            'submission.schema.json','audit-method.md','target-support','build-inputs','agent-inputs'):
        assert json.dumps(str(tmp_path/path))+'="read"' in options
    assert 'default_permissions="ca_audit"' in options and 'permissions.ca_audit.filesystem=' in options
    assert json.dumps(str(tmp_path/'source')) not in options
    assert '":root"="deny"' in options and 'network.enabled=false' in options
    assert json.dumps(str(tmp_path/'draft'))+'="write"' in options
    assert json.dumps(str(tmp_path/'host-tmp'))+'="deny"' in options
    assert '":tmpdir"' not in options and '":slash_tmp"="deny"' in options


def test_source_view_only_exposes_authorized_snapshot_and_rejects_stale_range(tmp_path):
    source=tmp_path/'repo';source.mkdir()
    (source/'a.py').write_text('def a():\n    return 1\n');(source/'b.py').write_text('hidden')
    root=tmp_path/'run';root.mkdir()
    snapshot=capture(source,root/'source',analysis_roots=['a.py'])
    class Holder: pass
    e=Holder();e.root=root;e.state=Analysis(mode='mock',config={},snapshot=snapshot)
    prepare_agent_source(e)
    assert (root/'agent-source'/'a.py').is_file() and not (root/'agent-source'/'b.py').exists()
    ref=SourceRange(id='a',file='a.py',start_line=1,end_line=2,kind='code_observation')
    assert source_materials(e,[ref])[0].text.startswith('def a')
    (root/'source'/'a.py').write_text('changed')
    with pytest.raises(ValueError,match='version changed'):source_materials(e,[ref])


def test_one_audit_runtime_and_methods_match_product_interface(tmp_path):
    from consensus_assurance.workflow.audit import method_text
    from consensus_assurance.workflow.prompts import loaded_resources
    from audit_support import engine_for, stop
    paths,text=method_text()
    selection=loaded_resources()
    e,repo=engine_for(tmp_path,[stop]);state=e.start(repo)
    assert paths==selection['paths']==state.method_paths
    assert state.framework_revision==selection['manifest_version']
    assert (e.root/'audit-method.md').read_text()==text
    resource_root=Path('src/consensus_assurance/resources')
    assert text=='\n'.join((resource_root/p).read_text() for p in paths)
    assert paths==['system.md','skills/consensus-analysis/SKILL.md','skills/evidence-review/SKILL.md','tasks/audit.md']


def test_submission_symlink_swap_cannot_change_the_read_target(tmp_path,monkeypatch):
    import consensus_assurance.workflow.audit as audit
    draft=tmp_path/'draft';draft.mkdir()
    source=draft/'submission.json';source.write_text('{}')
    private=tmp_path/'private';private.write_text('private content')
    real_check=audit.draft_file
    def swap(root,name):
        path=real_check(root,name)
        path.unlink();path.symlink_to(private)
        return path
    monkeypatch.setattr(audit,'draft_file',swap)
    with pytest.raises(OSError):audit.draft_bytes(draft,'submission.json')


@pytest.mark.parametrize('events,session,reason',[
    ([{'type':'turn.completed'}],None,'session identity'),
    ([{'type':'thread.started','thread_id':'different'},{'type':'turn.completed'}],'saved','identity changed'),
    ([{'type':'thread.started','thread_id':'saved'}],'saved','completed event')])
def test_incomplete_or_changed_agent_session_is_not_a_success(tmp_path,events,session,reason):
    log=tmp_path/'events.jsonl';log.write_text('\n'.join(json.dumps(e) for e in events))
    response=tmp_path/'response.json';response.write_text(json.dumps({'submission':'draft.json','summary':'Claimed complete'}))
    check=CheckRun(action='agent_turn',cwd=str(tmp_path),snapshot_id='fixture',status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
    check,_,result=CodexAgent().decode(check,response,session)
    assert check.status==ExecutionStatus.ERROR and reason in check.reason and result is None


def test_helper_preflight_rejects_aliases_collisions_and_target_replacement(tmp_path):
    from consensus_assurance.adapters.runners.experiment import install_harness
    from consensus_assurance.core.types import Harness
    (tmp_path/'target.py').write_text('original')
    for files in ({'main.py':'replacement'}, {'a/./x.py':'one','a/x.py':'two'},
            {'helper':'file','helper/a.py':'nested'}, {'target.py':'replacement'},
            {'../escape.py':'escape'}, {'go.mod':'module changed'}):
        harness=Harness(kind='python',source='print(1)',files=files,description='Assembly boundary fixture',semantic_changes=[])
        with pytest.raises(ValueError):install_harness(tmp_path,'main.py',harness,{'target.py':'captured'})
        assert [p.name for p in tmp_path.iterdir()]==['target.py']
        assert (tmp_path/'target.py').read_text()=='original'


def test_failed_permission_preflight_spends_no_agent_call(tmp_path):
    from audit_support import engine_for,first
    engine,repo=engine_for(tmp_path,[first])
    engine.agent.prepare=lambda *args:(False,[])
    state=engine.start(repo)
    assert state.usage.get('agent_calls',0)==0 and not state.agent_turns
    assert 'no model payload sent' in state.stop_reason


def test_provider_configuration_and_catalog_inputs_precede_cached_results(tmp_path,monkeypatch):
    from audit_support import engine_for
    from consensus_assurance.cli import load_config
    from consensus_assurance.core.config import Config,CodexProvider
    cfg=load_config('configs/targets/deepseek.example.yaml')
    assert not cfg.allow_agent_materials and not cfg.allow_experiments
    assert Path(cfg.codex_provider.model_catalog_path).is_absolute()
    raw=cfg.codex_provider.model_dump(mode='json')
    for fields in ({'id':'openai'},{'id':'other.headers'},{'id':'bad\nname'},
            {'base_url':'http://api.deepseek.com'},{'base_url':'https://user:password@api.deepseek.com'},
            {'base_url':'https://api.deepseek.com?key=not-a-key'},{'base_url':'https://api.deepseek.com/#fragment'},
            {'base_url':'https://api.deepseek.com?'},{'base_url':'https://api.deepseek.com:invalid'},
            {'env_key':'TOKEN=not-a-key'},{'env_key':'PATH'},{'env_key':'https_proxy'},
            {'experimental_bearer_token':'not-a-key'}):
        with pytest.raises(ValueError):CodexProvider.model_validate({**raw,**fields})
    for fields in ({'agent_model':None},{'agent_model':'--malicious'},{'agent_model':'bad\nname'},{'agent_backend':'mock'}):
        with pytest.raises(ValueError):Config.model_validate({**cfg.model_dump(mode='json'),**fields})
    catalog=tmp_path/'trusted-models.json';catalog.write_bytes(Path(cfg.codex_provider.model_catalog_path).read_bytes())
    e,repo=engine_for(tmp_path,[])
    e.config.agent_backend='codex';e.config.agent_model=cfg.agent_model;e.config.agent_reasoning_effort='low'
    e.config.codex_provider=cfg.codex_provider.model_copy(update={'model_catalog_path':str(catalog)})
    e.agent=CodexAgent('low',cfg.agent_model,e.config.codex_provider)
    e.config.budget.agent_calls=1
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    e.start(repo,plan_only=True)
    frozen=e.root/'agent-inputs/models.json'
    assert frozen.read_bytes()==catalog.read_bytes() and not frozen.stat().st_mode & 0o222
    assert 'model_catalog_json='+json.dumps(str(frozen)) in e.agent.connection_options(e.root)
    with pytest.raises(ValueError,match='Missing provider credential'):
        e.agent.prepare(e.runner,e.root/'draft','fixture')
    assert e.state.usage.get('agent_calls',0)==0
    e.agent.version='fixture-cli-v1';e.state.tools['agent']=e.agent.version
    from consensus_assurance.adapters.storage.files import write_json
    write_json(e.root/'logs/fixture/check.json',CheckRun(action='agent_turn',cwd=str(e.root/'draft'),snapshot_id='fixture',
        command=['codex','exec','--ignore-user-config',*e.agent.connection_options(e.root)]))
    check=CheckRun(action='agent_turn',cwd=str(e.root/'draft'),snapshot_id='fixture',
        status=ExecutionStatus.CANCELLED,reason='Fixture cancellation')
    result=e.action('agent_turn','agent_calls',lambda:[check.model_dump(mode='json'),None,None],{'turn':1})
    saved={p:p.read_bytes() for p in e.root.rglob('*') if p.is_file()}
    def reused():return e.action('agent_turn','agent_calls',lambda:pytest.fail('Cached action executed'),{'turn':1})
    assert reused()==result
    for name,value in [('agent_model','another-model'),('agent_reasoning_effort','high'),('codex_profile','single_agent'),
            ('codex_provider',e.config.codex_provider.model_copy(update={'base_url':'https://other.example'}))]:
        original=getattr(e.config,name);setattr(e.config,name,value)
        with pytest.raises(ValueError,match='connection changed'):reused()
        setattr(e.config,name,original)
    original=catalog.read_bytes();catalog.write_bytes(original+b'\n')
    assert reused()==result and all(p.read_bytes()==v for p,v in saved.items())
    from consensus_assurance.workflow.audit import execute
    with monkeypatch.context() as context:
        context.setattr(e,'probe_tools',lambda:None)
        assert e.resume().stop_reason == 'Agent stopped: Fixture cancellation'
        assert execute(e).stop_reason == 'Agent stopped: Fixture cancellation'
    assert frozen.read_bytes()==original
    assert 'model_catalog_json='+json.dumps(str(frozen)) in e.agent.connection_options(e.root)
    saved={p:p.read_bytes() for p in e.root.rglob('*') if p.is_file()}
    frozen.chmod(0o644);frozen.write_bytes(original+b'\n')
    with pytest.raises(ValueError,match='catalog changed'):reused()
    with pytest.raises(ValueError,match='catalog changed'):e.resume()
    with pytest.raises(ValueError,match='catalog changed'):execute(e)
    frozen.write_bytes(original);frozen.chmod(0o444)
    e.agent.version='fixture-cli-v2'
    with pytest.raises(ValueError,match='CLI version changed'):reused()
    e.agent.version='fixture-cli-v1'
    monkeypatch.setattr(e.agent,'probe',lambda runner:{'version':'fixture-cli-v2','available':True,'checks':[]})
    with pytest.raises(ValueError,match='CLI version changed'):e.resume()
    assert reused()==result and all(p.read_bytes()==v for p,v in saved.items())
    assert e.state.usage['agent_calls']==1


def test_provider_client_environment_and_error_redaction_do_not_reach_target(tmp_path,monkeypatch):
    import os,sys
    from consensus_assurance.core.config import CodexProvider
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.adapters.runners.experiment import clean_environment
    secret='unlabelled-client-canary-7890123456'
    monkeypatch.setenv('PROVIDER_TICKET',secret)
    root=tmp_path/'run';runner=ProcessRunner(root);draft=root/'draft'
    client=tmp_path/'client.py';client.write_text('''import json,os
assert 'PROVIDER_TICKET' in os.environ
print(json.dumps({'type':'thread.started','thread_id':'canary-session'}))
print(json.dumps({'type':'turn.failed','error':{'message':'Client diagnostic '+os.environ['PROVIDER_TICKET']}}))
''')
    agent=CodexAgent('low','deepseek-flash',CodexProvider(id='deepseek',base_url='https://api.deepseek.com',env_key='PROVIDER_TICKET'))
    agent.available=True;agent.version='fixture-client';agent.sandbox_command=lambda root:[sys.executable,str(client)]
    agent.permission_probe=lambda *args:(True,[])
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    agent.prepare(runner,draft,'fixture')
    check,_,result=agent.investigate(runner,'Neutral fixture',draft,'fixture',10)
    assert result is None and check.status==ExecutionStatus.ERROR and '[REDACTED]' in check.reason
    assert all(secret.encode() not in p.read_bytes() for p in root.rglob('*') if p.is_file())
    workspace=root/'workspace';workspace.mkdir()
    check=runner.run([sys.executable,'-c',"import os; assert 'PROVIDER_TICKET' not in os.environ; print('CREDENTIAL_ABSENT')"],
        workspace,'target-environment','fixture',10,env=clean_environment(workspace))
    assert check.exit_code==0 and Path(check.stdout).read_text().strip()=='CREDENTIAL_ABSENT'


def test_selected_profile_is_bound_once_and_requires_retained_home(tmp_path, monkeypatch):
    from consensus_assurance.core.config import Config
    home = tmp_path/'private-home'; home.mkdir()
    monkeypatch.setenv('CODEX_HOME', str(home))
    agent = CodexAgent('high', 'fixture-model', profile='single_agent')
    agent.bind_inputs(tmp_path, tmp_path/'source')
    calls = []
    class Runner:
        root = tmp_path
        def run(self, command, directory, action, snapshot, timeout, **kwargs):
            calls.append(action)
            skill = home/'skills/system/SKILL.md'; skill.parent.mkdir(parents=True, exist_ok=True); skill.write_text('fixture')
            return CheckRun(action=action, cwd=str(directory), snapshot_id=snapshot,
                status=ExecutionStatus.COMPLETED, exit_code=0)
    runner = Runner()
    monkeypatch.setattr(CodexAgent, 'permission_options', lambda *args: [])
    monkeypatch.setattr(CodexAgent, 'permission_probe', lambda *args: (True, []))
    assert agent.prepare(runner, tmp_path/'draft', 's')[0]
    path = tmp_path/'agent-inputs/runtime-settings.json'; raw = path.read_bytes()
    cfg = Config(agent_model='fixture-model', agent_reasoning_effort='high', codex_profile='single_agent')
    restored = CodexAgent('high', 'fixture-model', profile='single_agent')
    restored.validate_inputs(tmp_path, cfg)
    assert restored.prepare(runner, tmp_path/'draft', 's')[0]
    assert path.read_bytes() == raw and calls == ['codex_profile_bootstrap']
    assert restored.profile_settings['skills.config'] == [{'path': str(skill), 'enabled': False}
        for skill in home.glob('skills/**/SKILL.md')]
    monkeypatch.setenv('CODEX_HOME', str(tmp_path/'another-home'))
    with pytest.raises(ValueError, match='environment differs'):restored.validate_inputs(tmp_path, cfg)
    # The default path creates no pairing record or bootstrap, regardless of old archives.
    default = CodexAgent()
    other = tmp_path/'default'; other.mkdir()
    default.bind_inputs(other, tmp_path/'source')
    assert default.prepare(runner, other/'draft', 's')[0]
    assert not (other/'agent-inputs').exists() and calls == ['codex_profile_bootstrap']
