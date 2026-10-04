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


def test_audit_failure_reason_preserves_schema_diagnostic_and_redacts_secrets():
    error='ERROR: '+json.dumps({'error':{'code':'invalid_json_schema','message':'Unsupported schema'}})
    assert failure_reason(error)=='Agent output schema rejected (invalid_json_schema): Unsupported schema'
    reason=failure_reason('Transport failed: api_key=fixture-secret '+('x'*1200))
    assert 'fixture-secret' not in reason and '[REDACTED]' in reason and len(reason)<1100


@pytest.mark.parametrize('session_id',[None,'exact-session'])
def test_new_session_or_exact_resume_counts_unique_completed_tool_items(tmp_path,monkeypatch,session_id):
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    class Runner:
        root=tmp_path
        active_action_id='operation'
        def run(self,command,cwd,action,snapshot_id,timeout,stdin=None):
            self.command=command
            log=tmp_path/'events.jsonl'
            events=[{'type':'thread.started','thread_id':'exact-session'},
                {'type':'item.started','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.updated','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'tool-1','type':'command_execution'}},
                {'type':'item.completed','item':{'id':'answer','type':'agent_message'}},
                {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
            log.write_text('\n'.join(json.dumps(e) for e in events))
            response=Path(command[command.index('--output-last-message')+1]);response.write_text(json.dumps({'submission':'submission.json','summary':'Done'}))
            return CheckRun(action=action,cwd=str(cwd),snapshot_id=snapshot_id,status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
    runner=Runner();agent=CodexAgent('low','gpt-6-astra');agent.available=True;agent.version='fixture-cli'
    agent.sandbox_command=lambda root:['codex']
    agent.permission_probe=lambda *a:(True,[])
    agent.prepare(runner,tmp_path/'draft','snapshot')
    check,session,result=agent.investigate(runner,'Investigate',tmp_path/'draft','snapshot',10,session_id)
    assert session=='exact-session' and result['submission']=='submission.json'
    assert runner.command[:2]==['codex','exec'] and ('resume' in runner.command)==bool(session_id)
    assert not {'--ignore-rules','--ephemeral','--last','fork'} & set(runner.command)
    assert '--ignore-user-config' in runner.command
    assert {'memories.use_memories=false','memories.generate_memories=false'} <= set(runner.command)
    assert check.parameters['agent_tool_events']==1 and check.parameters['agent_usage']['input_tokens']==10
    assert ('exact-session' in runner.command)==bool(session_id) and 'model_reasoning_effort="low"' in runner.command


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
    for path in ('agent-source','submissions','logs','direct-checks','actions','state.json','research.json',
            'submission.schema.json','product-schemas.json','audit-method.md','target-support','build-inputs'):
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
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.prompts import loaded_resources
    from audit_support import engine_for, stop
    root=Path('src/consensus_assurance/workflow')
    for name in ('discovery','inquiry','agent_tasks','task_packet','output_repair','staged_model','native'):
        assert not (root/(name+'.py')).exists()
    assert not hasattr(Engine,'ask') and not hasattr(Engine,'targeted_read')
    paths,text=method_text()
    selection=loaded_resources()
    e,repo=engine_for(tmp_path,[stop]);state=e.start(repo)
    assert paths==selection['paths']==state.method_paths
    assert state.framework_revision==selection['manifest_version']
    assert (e.root/'audit-method.md').read_text()==text
    resource_root=Path('src/consensus_assurance/resources')
    assert text=='\n'.join((resource_root/p).read_text() for p in paths)
    assert {'system.md','skills/consensus-analysis/guide.md',
        'skills/consensus-analysis/references/behavior-facts.md','tasks/audit.md'}<=set(paths)


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
    from consensus_assurance.core.proposals import Harness
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
