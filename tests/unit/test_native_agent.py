"""Native transport protocol, local permission preflight and source boundaries."""
import json
from pathlib import Path
import pytest
from consensus_assurance.adapters.agents.backend import CodexAgent, classify_failure
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Analysis
from consensus_assurance.workflow.native import NativeSubmission, prepare_native_source, source_materials, SourceRange
from consensus_assurance.adapters.storage.snapshot import capture


@pytest.mark.parametrize('message,expected',[('Please log in; 401',ExecutionStatus.LOGIN_REQUIRED),
    ('insufficient_quota',ExecutionStatus.QUOTA_EXHAUSTED),('bad transport',ExecutionStatus.ERROR)])
def test_native_auth_quota_failure(message,expected):
    assert classify_failure(message)==expected


def test_resume_uses_exact_id_and_counts_unique_completed_tool_items(tmp_path,monkeypatch):
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
    check,session,result=agent.investigate(runner,'Continue',tmp_path/'draft','snapshot',10,'exact-session')
    assert session=='exact-session' and result['submission']=='submission.json'
    assert runner.command[:3]==['codex','exec','resume']
    assert '--ignore-rules' not in runner.command and '--ephemeral' not in runner.command
    assert check.parameters['native_tool_events']==1 and check.parameters['native_usage']['input_tokens']==10
    assert 'exact-session' in runner.command and 'model_reasoning_effort="low"' in runner.command


def test_probe_bootstrap_crash_does_not_prove_denial(tmp_path,monkeypatch):
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    source=tmp_path/'native-source';source.mkdir();(source/'test.py').write_text('safe')
    draft=tmp_path/'draft';draft.mkdir()
    class Runner:
        root=tmp_path
        def run(self,*args,**kwargs):
            return CheckRun(action='native_permission_probe',cwd=str(draft),snapshot_id='s',status=ExecutionStatus.COMPLETED,exit_code=1)
    agent=CodexAgent();ok,checks=agent.prepare(Runner(),draft,'s')
    assert not ok and checks[0].parameters['permission_result']=='inconclusive_or_unsafe'
    with pytest.raises(RuntimeError,match='before reserving'):
        agent.available=True
        agent.investigate(Runner(),'source',draft,'s',1)


def test_effective_profile_exposes_results_and_retains_root_network_boundary(tmp_path,monkeypatch):
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    options='\n'.join(CodexAgent().permission_options(tmp_path,tmp_path/'draft'))
    for path in ('logs','models','direct-checks','actions','state.json','research.json','product-schemas.json','native-method.md'):
        assert json.dumps(str(tmp_path/path))+'="read"' in options
    assert '":root"="deny"' in options and 'network.enabled=false' in options
    assert json.dumps(str(tmp_path/'draft'))+'="write"' in options


def test_source_view_only_exposes_authorized_snapshot_and_rejects_stale_range(tmp_path):
    source=tmp_path/'repo';source.mkdir()
    (source/'a.py').write_text('def a():\n    return 1\n');(source/'b.py').write_text('hidden')
    root=tmp_path/'run';root.mkdir()
    snapshot=capture(source,root/'source',analysis_roots=['a.py'])
    class Holder: pass
    e=Holder();e.root=root;e.state=Analysis(mode='mock',config={},snapshot=snapshot)
    prepare_native_source(e)
    assert (root/'native-source'/'a.py').is_file() and not (root/'native-source'/'b.py').exists()
    ref=SourceRange(id='a',file='a.py',start_line=1,end_line=2,kind='code_observation')
    assert source_materials(e,[ref])[0].text.startswith('def a')
    (root/'source'/'a.py').write_text('changed')
    with pytest.raises(ValueError,match='version changed'):source_materials(e,[ref])


def test_one_native_runtime_and_methods_match_product_interface():
    import ast
    from consensus_assurance.workflow.native import method_text
    from consensus_assurance.workflow.engine import Engine
    root=Path('src/consensus_assurance/workflow')
    for name in ('discovery','inquiry','agent_tasks','task_packet','output_repair','staged_model'):
        assert not (root/(name+'.py')).exists()
    assert not hasattr(Engine,'ask') and not hasattr(Engine,'targeted_read')
    paths,text=method_text()
    assert 'Use native' in text and 'previous_check_id' in text and 'product-schemas.json' in text
    assert all((Path('src/consensus_assurance/resources')/p).is_file() for p in paths)
    assert 'key/value_json' not in text and 'previous_reply' not in text
    for answer in ('hashicorp','swiftpaxos','fixture_value','v16','v20'):
        assert answer not in text.lower()


def test_submission_symlink_swap_cannot_change_the_read_target(tmp_path,monkeypatch):
    import consensus_assurance.workflow.native as native
    draft=tmp_path/'draft';draft.mkdir()
    source=draft/'submission.json';source.write_text('{}')
    private=tmp_path/'private';private.write_text('private content')
    real_check=native.draft_file
    def swap(root,name):
        path=real_check(root,name)
        path.unlink();path.symlink_to(private)
        return path
    monkeypatch.setattr(native,'draft_file',swap)
    with pytest.raises(OSError):native.draft_bytes(draft,'submission.json')


@pytest.mark.parametrize('events,session,reason',[
    ([{'type':'turn.completed'}],None,'session identity'),
    ([{'type':'thread.started','thread_id':'different'},{'type':'turn.completed'}],'saved','identity changed'),
    ([{'type':'thread.started','thread_id':'saved'}],'saved','completed event')])
def test_incomplete_or_changed_native_session_is_not_a_success(tmp_path,events,session,reason):
    log=tmp_path/'events.jsonl';log.write_text('\n'.join(json.dumps(e) for e in events))
    response=tmp_path/'response.json';response.write_text(json.dumps({'submission':'draft.json','summary':'Claimed complete'}))
    check=CheckRun(action='native_agent',cwd=str(tmp_path),snapshot_id='fixture',status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
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
    from native_support import engine_for,first
    engine,repo=engine_for(tmp_path,[first])
    engine.agent.prepare=lambda *args:(False,[])
    state=engine.start(repo)
    assert state.usage.get('agent_calls',0)==0 and not state.native_turns
    assert 'no model payload sent' in state.stop_reason
