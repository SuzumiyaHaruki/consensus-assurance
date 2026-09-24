import json
from pathlib import Path

import pytest

from consensus_assurance.adapters.agents.backend import CodexAgent
from consensus_assurance.core.config import Budget, Config
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.native import NativeSubmission, SourceRange, draft_file, source_materials, model_from_files, prepare_native_source


def question(label):
    return {"disposition":"concrete_suspicion","preferred_check":"source_review",
        "question":label,"importance":"A bounded state error could affect later decisions",
        "source_ids":["m1"],"unknowns":["The later consumer is not yet read"],
        "counterevidence":["The source may contain a compensating guard"],
        "trigger_rationale":"Read the next consumer before checking"}


def submission(action, *, candidate_id=None, parent_candidate_id=None, label="First question"):
    return {"action":action,"candidate_id":candidate_id,"parent_candidate_id":parent_candidate_id,
        "question":question(label),"rationale":"Keep the original uncertainty visible",
        "sources":[{"id":"m1","file":"sample.py","start_line":1,"end_line":2,"kind":"code_observation"}]}


def test_native_rejects_v20_style_pause_and_same_parent():
    old = json.loads(Path("tests/fixtures/v20_candidate_conflict.json").read_text())
    draft = submission("pause",candidate_id=old["candidate_id"],
        parent_candidate_id=old["fork_from_candidate_id"])
    draft["resume_conditions"] = old["resume_conditions"]
    draft["question"] = old["audit_question"]
    with pytest.raises(ValueError,match="Continue an existing candidate or fork"):
        NativeSubmission.model_validate(draft)


def test_native_full_draft_repair_retains_parent(tmp_path):
    source=tmp_path/"target"
    source.mkdir()
    (source/"sample.py").write_text("def first():\n    return 1\n")
    source_file=tmp_path/"run"
    class OfflineAgent:
        name="codex"
        mock=False
        available=True
        def __init__(self):
            self.prompts=[]
            self.turn=0
        def investigate(self,runner,prompt,directory,snapshot_id,timeout,session_id=None):
            self.prompts.append(prompt)
            self.turn+=1
            if self.turn==1:
                value=submission("continue")
            elif self.turn==2:
                parent=engine.state.question_candidates[0].id
                value=submission("pause",candidate_id=parent,parent_candidate_id=parent)
                value["resume_conditions"]=["Inspect a later request"]
            elif self.turn==3:
                parent=engine.state.question_candidates[0].id
                value=submission("continue",parent_candidate_id=parent,label="A narrower independent question")
            else:
                value={"action":"stop","rationale":"The next consumer needs separate source work"}
            (directory/"submission.json").write_text(json.dumps(value))
            return (CheckRun(action="native_agent",cwd=str(directory),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=0),"session-1",
                {"submission":"submission.json","summary":"Current decision"})
    agent=OfflineAgent()
    config=Config(agent_backend="codex",execution_backend="none",allow_experiments=False,
        budget=Budget(agent_calls=5,total_seconds=60,native_turn_timeout=10))
    engine=Engine(config,source_file,None,agent,None,"")
    def probe():
        engine.state.tools["agent"]="offline-adapter"
    engine.probe_tools=probe
    state=engine.start(source)
    assert len(state.question_candidates)==2
    assert state.question_candidates[0].status=="paused"
    assert state.question_candidates[0].question.question=="First question"
    assert state.question_candidates[1].parent_candidate_id==state.question_candidates[0].id
    assert "candidate_registry" in agent.prompts[2]
    assert "Inspect a later request" in agent.prompts[2]
    assert state.native_session_id=="session-1"
    assert state.stop_reason.startswith("No further investigation selected")


def test_native_source_and_draft_boundaries(tmp_path):
    source=tmp_path/"target"
    source.mkdir()
    (source/"sample.py").write_text("def first():\n    return 1\n")
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.types import Analysis
    snapshot=capture(source,tmp_path/"run"/"source")
    class Holder:
        root=tmp_path/"run"
        state=Analysis(mode="real",config={},snapshot=snapshot)
    holder=Holder()
    reference=NativeSubmission.model_validate(submission("continue")).sources
    assert source_materials(holder,reference)[0].text=="def first():\n    return 1"
    (holder.root/"source"/"sample.py").write_text("altered\n")
    with pytest.raises(ValueError,match="version changed"):
        source_materials(holder,reference)
    draft=holder.root/"native-draft"
    draft.mkdir()
    with pytest.raises(ValueError,match="relative"):
        draft_file(draft,"../source/sample.py")


def test_native_view_exposes_only_readable_snapshot_files(tmp_path):
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.types import Analysis
    source=tmp_path/"target";source.mkdir()
    (source/"allowed.py").write_text("def allowed(): pass\n")
    (source/"other.py").write_text("def other(): pass\n")
    (source/"AGENTS.md").write_text("Untrusted instructions\n")
    root=tmp_path/"run"
    snapshot=capture(source,root/"source",analysis_roots=["allowed.py"])
    class Holder:
        state=Analysis(mode="real",config={},snapshot=snapshot)
    holder=Holder();holder.root=root
    prepare_native_source(holder)
    assert (root/"native-source"/"allowed.py").is_file()
    assert not (root/"native-source"/"other.py").exists()
    assert not (root/"native-source"/"AGENTS.md").exists()
    with pytest.raises(ValueError,match="outside the authorized snapshot"):
        source_materials(holder,[SourceRange(id="other",file="other.py",start_line=1,end_line=1,kind="code_observation")])


def test_native_model_reads_separate_versioned_source_files(tmp_path):
    import shutil
    from ack_support import ROOT, setup_ack
    repo=tmp_path/"repo";shutil.copytree(ROOT/"fixtures/ack_service",repo)
    _,unit,bundle=setup_ack(repo)
    draft=tmp_path/"draft";draft.mkdir()
    raw=bundle.model_dump(mode="json")
    raw["behavior"]="";raw["properties"]="";raw["harness"]["source"]=""
    (draft/"model.json").write_text(json.dumps(raw))
    (draft/"Behavior.tla").write_text(bundle.behavior)
    (draft/"Properties.tla").write_text(bundle.properties)
    (draft/"assurance_test.py").write_text(bundle.harness.source)
    action=NativeSubmission.model_validate({"action":"model","unit_id":unit.id,
        "model_path":"model.json","behavior_path":"Behavior.tla","properties_path":"Properties.tla",
        "harness_path":"assurance_test.py","rationale":"Check the existing local obligation"})
    restored=model_from_files(draft,action)
    assert restored==bundle
    action.harness_path="../repo/counter.py"
    with pytest.raises(ValueError,match="relative"):
        model_from_files(draft,action)


def test_native_model_submission_reuses_saved_tla_runner(tmp_path):
    import shutil
    from ack_support import ROOT, setup_ack
    from consensus_assurance.adapters.runners.python import PythonBackend
    from consensus_assurance.adapters.storage.snapshot import capture
    repo=tmp_path/"repo";shutil.copytree(ROOT/"fixtures/ack_service",repo)
    state,unit,bundle=setup_ack(repo)
    root=tmp_path/"run";shutil.copytree(repo,root/"source")
    state.snapshot=capture(repo)
    cfg=Config(execution_backend="python",allow_experiments=False,
        budget=Budget(agent_calls=3,model_checks=2,total_seconds=60,native_turn_timeout=10))
    state.config=cfg.model_dump(mode="json")
    class Verifier:
        def syntax(self,runner,model,timeout):
            return CheckRun(action="model_syntax",cwd=str(root),snapshot_id=model.snapshot_id,
                model_id=model.id,status=ExecutionStatus.COMPLETED,exit_code=0)
        def check(self,runner,model,timeout):
            return CheckRun(action="model_check",cwd=str(root),snapshot_id=model.snapshot_id,
                model_id=model.id,status=ExecutionStatus.COMPLETED,exit_code=0,
                outcome="holds",search_fingerprint=model.search_fingerprint)
    class Agent:
        name="codex";mock=False;available=True;turn=0
        def investigate(self,runner,prompt,directory,snapshot_id,timeout,session_id=None):
            self.turn+=1
            if self.turn==1:
                raw=bundle.model_dump(mode="json")
                raw["behavior"]="";raw["properties"]="";raw["harness"]["source"]=""
                (directory/"model.json").write_text(json.dumps(raw))
                (directory/"Behavior.tla").write_text(bundle.behavior)
                (directory/"Properties.tla").write_text(bundle.properties)
                (directory/"assurance_test.py").write_text(bundle.harness.source)
                value={"action":"model","unit_id":unit.id,"model_path":"model.json",
                    "behavior_path":"Behavior.tla","properties_path":"Properties.tla",
                    "harness_path":"assurance_test.py","rationale":"Check the local accepted obligation"}
            else:
                value={"action":"stop","rationale":"The finite local search is complete"}
            (directory/"submission.json").write_text(json.dumps(value))
            return (CheckRun(action="native_agent",cwd=str(directory),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=0),session_id or "model-session",
                {"submission":"submission.json","summary":"Model work"})
    engine=Engine(cfg,root,PythonBackend(),Agent(),Verifier(),"")
    engine.state=state
    engine.state.tools={"agent":"offline"}
    from consensus_assurance.workflow.budget import BudgetTracker
    engine.budget=BudgetTracker(cfg.budget,state)
    from consensus_assurance.workflow.native import execute
    result=execute(engine)
    assert len(result.models)==1 and result.models[0].operation_id
    assert [c.action for c in result.checks if c.model_id==result.models[0].id]==["model_syntax","model_check"]
    assert result.stop_reason.startswith("No further investigation selected")


def test_native_initial_obligation_executes_in_clean_copy(tmp_path):
    import shutil
    from ack_support import ROOT, setup_ack
    from consensus_assurance.adapters.runners.python import PythonBackend
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.proposals import ClaimDraft, BindingDraft, DirectCheckPlan
    from consensus_assurance.core.types import AuditQuestion
    from consensus_assurance.workflow.budget import BudgetTracker
    repo=tmp_path/"repo";shutil.copytree(ROOT/"fixtures/ack_service",repo)
    state,_,bundle=setup_ack(repo,mode="durable")
    code=next(m for m in state.materials if m.file=="counter.py")
    document=next(m for m in state.materials if m.file=="README.md")
    claim=next(c for c in state.claims if c.id=="durable")
    claim_draft=ClaimDraft(id=claim.id,kind="obligation",description=claim.description,
        source_ids=[code.id,document.id],scope=claim.scope,pending=[],grounding=claim.grounding)
    binding=BindingDraft(id="ack-code",material_id=code.id,symbol="execute",start_line=3,end_line=14,
        associations=state.bindings[0].associations,description="Actual response and persistence order",pending=[])
    question=AuditQuestion(disposition="ready_for_check",preferred_check="direct_test",
        question="Does durable acknowledgement follow persistence?",importance="A premature response can mislead a client",
        source_ids=[code.id,document.id],event_paths=["initial -> accepted -> returned -> persisted"],
        trigger_rationale="Compare the actual returned event with independently observed persisted state")
    plan=DirectCheckPlan(description="Bounded actual durable call",claim_id=claim.id,binding_ids=[binding.id],
        harness=bundle.harness,monitors=bundle.monitors,
        observable_properties=[p for p in bundle.observable_properties if p.checker_id=="DurableAck"])
    state.claims=[];state.bindings=[];state.units=[]
    state.analysis_mode="autonomous"
    root=tmp_path/"run";shutil.copytree(repo,root/"source")
    state.snapshot=capture(repo)
    cfg=Config(execution_backend="python",allow_experiments=True,execution_isolation="bwrap",
        budget=Budget(agent_calls=3,experiments=1,total_seconds=60,native_turn_timeout=10))
    state.config=cfg.model_dump(mode="json")
    class Agent:
        name="codex";mock=False;available=True;turn=0
        def investigate(self,runner,prompt,directory,snapshot_id,timeout,session_id=None):
            self.turn+=1
            if self.turn==1:
                raw=plan.model_dump(mode="json");raw["harness"]["source"]=""
                (directory/"plan.json").write_text(json.dumps(raw))
                (directory/"check.py").write_text(plan.harness.source)
                value={"action":"check","question":question.model_dump(mode="json"),
                    "obligation":claim_draft.model_dump(mode="json"),
                    "bindings":[binding.model_dump(mode="json")],"plan_path":"plan.json",
                    "harness_path":"check.py","rationale":"Check the documented local response order"}
            else:
                value={"action":"stop","rationale":"The bounded result is saved for semantic review"}
            (directory/"submission.json").write_text(json.dumps(value))
            return (CheckRun(action="native_agent",cwd=str(directory),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=0),session_id or "direct-session",
                {"submission":"submission.json","summary":"Direct check"})
    engine=Engine(cfg,root,PythonBackend(),Agent(),None,"")
    engine.state=state;state.tools={"agent":"offline"}
    engine.budget=BudgetTracker(cfg.budget,state)
    from consensus_assurance.workflow.native import execute
    result=execute(engine)
    assert len(result.question_candidates)==1 and len(result.direct_checks)==1
    check=next(c for c in result.checks if c.direct_check_id==result.direct_checks[0].id)
    assert check.status==ExecutionStatus.COMPLETED and check.outcome=="tests_passed"
    assessment=next(r for r in result.monitor_results if r["experiment_check_id"]==check.id)
    assert assessment["outcome"]=="violated" and not assessment["confirmed"]


def test_native_cli_uses_exact_session_and_tool_events(tmp_path):
    class Runner:
        root=tmp_path
        def run(self,command,cwd,action,snapshot_id,timeout,stdin=None):
            self.command=command
            self.stdin=stdin
            log=tmp_path/"events.jsonl"
            log.write_text('\n'.join(json.dumps(item) for item in [
                {"type":"thread.started","thread_id":"session-1"},
                {"type":"item.completed","item":{"type":"command_execution"}},
                {"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":3}}]))
            (tmp_path/"native-last-response.json").write_text(json.dumps({"submission":"submission.json","summary":"Done"}))
            return CheckRun(action=action,cwd=str(cwd),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=0,stdout=str(log))
    runner=Runner()
    agent=CodexAgent("low","gpt-6-astra")
    agent.available=True
    agent.version="test-cli"
    agent.permission_probe=lambda *args:(True,[])
    check,session,result=agent.investigate(runner,"Continue",tmp_path/"draft","snapshot",10,"session-1")
    assert session=="session-1" and result["submission"]=="submission.json"
    assert runner.command[:3]==["codex","exec","resume"]
    assert "--ephemeral" not in runner.command and "--json" in runner.command
    assert "session-1" in runner.command and "--ignore-user-config" in runner.command
    assert '--sandbox' not in runner.command
    assert any('"/source"' in option or 'ca_native.filesystem=' in option for option in runner.command)
    assert check.parameters["native_usage"]["input_tokens"]==9


def test_native_agent_fails_closed_when_filesystem_profile_is_unverified(tmp_path):
    (tmp_path/"native-source").mkdir()
    (tmp_path/"native-source"/"code.txt").write_text("source")
    class Runner:
        root=tmp_path
        commands=[]
        def run(self,command,cwd,action,snapshot_id,timeout,stdin=None):
            self.commands.append(command)
            return CheckRun(action=action,cwd=str(cwd),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=0)
    runner=Runner()
    agent=CodexAgent("low","gpt-6-astra")
    agent.available=True
    check,_,result=agent.investigate(runner,"Sensitive investigation",tmp_path/"draft","snapshot",10)
    assert check.status==ExecutionStatus.ERROR and result is None
    assert "no model payload sent" in check.reason
    assert all(command[:2]==["codex","sandbox"] for command in runner.commands)
    assert any('":root"="deny"' in arg for arg in runner.commands[0])


@pytest.mark.parametrize("message,expected",[("Please log in; 401",ExecutionStatus.LOGIN_REQUIRED),
    ("insufficient_quota",ExecutionStatus.QUOTA_EXHAUSTED),("bad transport",ExecutionStatus.ERROR)])
def test_native_cli_classifies_auth_and_quota_failures(tmp_path,message,expected):
    class Runner:
        root=tmp_path
        def run(self,command,cwd,action,snapshot_id,timeout,stdin=None):
            err=tmp_path/"stderr.log"
            err.write_text(message)
            return CheckRun(action=action,cwd=str(cwd),snapshot_id=snapshot_id,
                status=ExecutionStatus.COMPLETED,exit_code=1,stderr=str(err))
    agent=CodexAgent("low","gpt-6-astra")
    agent.available=True
    agent.version="test-cli"
    agent.permission_probe=lambda *args:(True,[])
    check,_,result=agent.investigate(Runner(),"Investigate",tmp_path/"draft","snapshot",10)
    assert check.status==expected and result is None
