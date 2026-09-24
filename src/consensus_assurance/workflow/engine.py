import json
import math
import shutil
import time
from pathlib import Path
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import (Analysis, Assessment, Calibration, CheckRun, Evidence,
    ExecutionStatus, Finding, Origin, Relation, uid, PendingAction, Record)
from consensus_assurance.ports.interfaces import AgentBackend, ExecutionBackend, VerifierBackend
from consensus_assurance.adapters.runners.process import ProcessRunner, output
from consensus_assurance.adapters.runners.experiment import run_experiment, install_harness
from consensus_assurance.adapters.storage.files import Store, write_json
from consensus_assurance.adapters.storage.snapshot import capture
from .budget import BudgetTracker
from .errors import Blocked
from .prompts import manifest

FRAMEWORK_REVISION = manifest()['version']

class Engine:
    def __init__(self, config: Config, root: Path, implementation: ExecutionBackend | None,
                 agent: AgentBackend, verifier: VerifierBackend, knowledge: str, inquiry: str = ""):
        self.config, self.root = config, root.resolve()
        self.implementation, self.agent, self.verifier = implementation, agent, verifier
        self.knowledge, self.inquiry = knowledge, inquiry
        self.store = Store(self.root)
        self.runner = ProcessRunner(self.root)
        self.state = None

    def checkpoint(self, event):
        self.budget.sync()
        versions={o.id:o.version for o in self.state.claims+self.state.bindings+self.state.relations+self.state.units}
        stale={a.id for a in self.state.direct_checks if any(versions.get(k)!=v for k,v in a.graph_versions.items())}
        for evidence in self.state.evidence:
            if evidence.direct_check_id in stale:
                evidence.applicability='recheck_required';evidence.assessment=Assessment.STALE;evidence.stale_reason='Direct-check semantic inputs changed'
        for finding in self.state.findings:
            if finding.direct_check_id in stale:finding.applicability='recheck_required'
        if stale:
            from .direct_checks import refresh_assessments
            refresh_assessments(self.state,stale,stale_only=True)
        from consensus_assurance.core.types import now
        observed={
            'initial_graph':bool(self.state.units),
            'scope_adopted':any(x['status']=='accepted' for x in self.state.scope_updates.values()),
            'scope_ready':any(u.semantic_readiness.get('status')=='reviewed' for u in self.state.units),
            'model_registered':bool(self.state.models),
            'model_draft_saved':any(m.stage=='model_only' for m in self.state.models),
            'harness_ready':any(m.stage=='complete' for m in self.state.models),
            'model_tool_execution':any(c.action=='model_check' and c.started_at for c in self.state.checks),
            'completed_search':any(c.action=='model_check' and c.status.value=='completed' and c.outcome in {'holds','counterexample'} for c in self.state.checks),
            'calibration_recorded':bool(self.state.calibrations),
            'implementation_evidence':any(e.level=='implementation_test' and e.origin.value=='executed' for e in self.state.evidence)}
        for key,seen in observed.items():
            if seen:self.state.milestones.setdefault(key,now())
        self.store.save(self.state, event)

    def start(self, repo, plan_only=False):
        if self.root.is_relative_to(repo.resolve()) or repo.resolve().is_relative_to(self.root):
            raise ValueError("Run and original target directories must be disjoint")
        started = time.monotonic()
        snapshot = capture(repo, self.root / "source", analysis_roots=self.config.target.analysis_roots, expected_module=self.config.target.expected_module)
        self.state = Analysis(framework_revision=FRAMEWORK_REVISION, mode="mock" if self.agent.mock else "real", config=self.config.model_dump(mode="json"), snapshot=snapshot)
        self.state.guidance = [{"source":"configured_reference","text":self.knowledge}]
        if self.inquiry:
            self.state.guidance.append({"source":"configured_inquiry","text":self.inquiry})
        self.state.analysis_mode = "regression" if self.agent.mock else ("directed" if self.config.directed_question else "autonomous")
        self.state.elapsed_seconds = time.monotonic() - started
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        write_json(self.root / "config.json", self.config)
        write_json(self.root / "snapshot.json", snapshot)
        self.checkpoint("created")
        if plan_only:
            self.state.stop_reason="Snapshot prepared; investigation requires run"
            self.checkpoint("plan_only")
            return self.state
        from .native import execute
        return execute(self)

    def resume(self, action_timeout=None, repair_attempts=None, native_turn_timeout=None):
        if repair_attempts is not None and (not isinstance(repair_attempts,int) or repair_attempts<0):raise ValueError("Repair attempt limit must be a nonnegative integer")
        if action_timeout is not None and (not math.isfinite(action_timeout) or action_timeout <= 0):
            raise ValueError("Action timeout must be a finite positive number")
        if native_turn_timeout is not None and (not math.isfinite(native_turn_timeout) or native_turn_timeout <= 0):
            raise ValueError("Native turn timeout must be a finite positive number")
        self.state = self.store.load()
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        if self.state.framework_revision!=FRAMEWORK_REVISION:
            self.state.stop_reason="Framework revision differs or was not recorded; preserve this historical run and use an explicit offline migration/subrun"
            return self.state
        if self.config.model_dump(mode="json") != self.state.config:
            self.state.stop_reason="Configuration changed; start a new run"
            self.checkpoint("resume_configuration_changed")
            return self.state
        if repair_attempts is not None and repair_attempts!=self.config.budget.repair_attempts:
            old=self.config.budget.repair_attempts
            data=self.config.model_dump(mode="json");data['budget']['repair_attempts']=repair_attempts
            self.config=Config.model_validate(data);self.state.config=self.config.model_dump(mode='json');self.budget.limits=self.config.budget
            self.checkpoint(f"repair_attempt_limit_changed:{old}:{repair_attempts}; usage and failures preserved")
        if action_timeout is not None and action_timeout != self.config.budget.action_timeout:
            old_timeout = self.config.budget.action_timeout
            data = self.config.model_dump(mode="json")
            data["budget"]["action_timeout"] = action_timeout
            self.config = Config.model_validate(data)
            self.state.config = self.config.model_dump(mode="json")
            self.budget.limits = self.config.budget
            self.checkpoint(f"resume_action_timeout_changed:{old_timeout}:{action_timeout}")
        if native_turn_timeout is not None and native_turn_timeout != self.config.budget.native_turn_timeout:
            old_timeout=self.config.budget.native_turn_timeout
            data=self.config.model_dump(mode="json");data["budget"]["native_turn_timeout"]=native_turn_timeout
            self.config=Config.model_validate(data);self.state.config=self.config.model_dump(mode="json")
            self.budget.limits=self.config.budget
            self.checkpoint(f"resume_native_turn_timeout_changed:{old_timeout}:{native_turn_timeout}")
        if self.agent.mock:
            self.agent.cursor = sum(1 for path in (self.root / "actions").glob("*/result.json")
                if isinstance(value := json.loads(path.read_text()), list) and value and isinstance(value[0], dict)
                and value[0].get("action") == "native_agent")
        old_tools = dict(self.state.tools)
        if self.budget.remaining() > 0:
            self.probe_tools()
        if old_tools and old_tools != self.state.tools:
            self.state.invalidate("Tool versions or availability changed")
            self.state.stop_reason = "Tool inputs changed; start a new run for revalidation"
            self.checkpoint("resume_tools_changed")
            return self.state
        pending = self.state.pending_action
        if pending and (self.root / "actions" / pending.id / "result.json").exists():
            pending.status = "completed"
        # Running actions with a completed raw receipt resume their existing operation.
        # Unknown outcomes receive a new identity only when action() schedules a retry.
        self.checkpoint("resumed")
        from .native import execute
        return execute(self)

    def record(self, check):
        if any(c.id == check.id for c in self.state.checks):
            return
        self.state.checks.append(check)
        write_json(self.root / "logs" / check.id / "check.json", check)
        self.checkpoint("execution_recorded")

    def probe_tools(self):
        for name, backend in [("agent", self.agent), ("verifier", self.verifier)]:
            if backend is None:
                continue
            self.budget.timeout()
            result = backend.probe(self.runner)
            self.state.tools[name] = result["version"]
            for check in result["checks"]:
                self.record(check)
                if check.action == "java_probe":
                    self.state.tools["java"] = output(check).strip()
            if not result["available"]:
                self.state.gaps.append(result["reason"])
        if self.implementation is None:return
        check = self.runner.run(self.implementation.version_command(), self.root, "implementation_tool_probe", self.state.snapshot.id, self.budget.timeout())
        self.record(check)
        self.state.tools["implementation"] = output(check).strip()

    def workspace(self):
        directory = self.root / "experiments" / (self.state.pending_action.id if self.state.pending_action else uid()) / "workspace"
        if not directory.exists():
            shutil.copytree(self.root / "source", directory)
        return directory

    def action(self, kind, resource, callback, inputs=None):
        from .action_identity import stable_input
        logical = stable_input(inputs or {})
        pending = self.state.pending_action
        same = pending and pending.kind == kind and pending.logical_input == logical
        if same and (self.root / "actions" / pending.id / "result.json").exists():
            return json.loads((self.root / "actions" / pending.id / "result.json").read_text())
        receipts = [CheckRun.model_validate_json(p.read_text()) for p in (self.root / "logs").glob("*/check.json")]
        recoverable = same and any(c.pending_action_id == pending.id and c.ended_at for c in receipts)
        if not recoverable:
            if pending:
                if pending.status == "running":
                    pending.status = "outcome_unknown"
                    self.state.gaps.append("Interrupted operation has no completed receipt; retry in a fresh workspace")
                self.state.action_history.append(pending.model_copy(deep=True))
            self.budget.take(resource)
            pending = PendingAction(kind=kind, logical_input=logical, unit_id=self.state.active_unit_id,
                model_id=self.state.active_model_id)
            self.state.pending_action = pending
        directory = self.root / "actions" / pending.id
        pending.input_path = str(directory / "input.json")
        write_json(Path(pending.input_path), inputs or {})
        pending.status = "running"
        self.runner.active_action_id = pending.id
        try:
            self.checkpoint("action_started")
            value = callback()
        finally:
            self.runner.active_action_id = None
        def pack(item):
            if isinstance(item, Record): return item.model_dump(mode="json")
            if isinstance(item, (tuple, list)): return [pack(x) for x in item]
            if isinstance(item, dict): return {k:pack(v) for k,v in item.items()}
            return item
        value = pack(value)
        write_json(directory / "result.json", value)
        pending.status = "completed"
        self.checkpoint("action_result_saved")
        return value

    def advance(self, stage):
        if self.state.pending_action:
            self.state.action_history.append(self.state.pending_action.model_copy(deep=True))
            self.state.pending_action = None
        self.state.next_action = stage
        self.checkpoint("next_action_" + stage)

    def experiment(self, model, bundle, replay=False):
        if not self.config.allow_experiments or self.implementation is None:
            raise Blocked("Target execution disabled or no execution backend configured; probes and replay unavailable")
        def execute():
            workspace=self.workspace()
            paths=install_harness(workspace,self.implementation.harness_filename,bundle.harness,self.state.snapshot.files)
            check=run_experiment(self.runner,self.implementation.experiment_command(),workspace,self.state.snapshot.id,
                self.budget.timeout(),self.config.execution_isolation,"replay" if replay else "experiment",adapter=self.implementation)
            check.model_id=model.id; check.input_versions=model.artifact_digests
            check.tool_version=self.state.tools.get("implementation","unknown")
            check.origin=Origin.MOCK if self.state.mode=="mock" else Origin.EXECUTED
            check.artifacts.extend([*paths,model.mapping_path])
            return check
        check=CheckRun.model_validate(self.action("replay" if replay else "experiment","experiments",execute,{"model_id":model.id,"bundle_path":model.bundle_path}))
        self.record(check)
        return check

    def calibrate(self, model, bundle, experiment):
        result=self.action("calibrate","calibration_checks",lambda:self.verifier.calibrate(self.runner,model,bundle,experiment,self.budget.timeout()),
            {"experiment_check_id":experiment.id,"model_id":model.id})
        record=Calibration.model_validate(result[0])
        for raw in result[1]: self.record(CheckRun.model_validate(raw))
        if not any(c.id==record.id for c in self.state.calibrations): self.state.calibrations.append(record)
        self.checkpoint("trace_calibration_recorded")
        return record

    def search(self, unit, model, bundle, calibration):
        from .inputs import reusable_search
        source=reusable_search(self.state,model)
        prior_reuse=next((c for c in reversed(self.state.checks) if c.model_id==model.id and c.action=="model_check" and c.reused_from and c.search_fingerprint==model.search_fingerprint),None)
        if source:
            check=source.model_copy(deep=True)
            check.id=uid();check.model_id=model.id;check.reused=True;check.reused_from=source.id
            check.input_versions=model.artifact_digests
            check.reason="Explicit reuse of identical search inputs from " + source.id
        elif prior_reuse:
            check=prior_reuse
        else:
            check=CheckRun.model_validate(self.action("model_search","model_checks",lambda:self.verifier.check(self.runner,model,self.budget.timeout()),{"model_id":model.id}))
        check.origin=Origin.MOCK if self.state.mode=="mock" else Origin.EXECUTED
        self.record(check)
        for result in check.checker_results:
            if result.outcome=="unknown" or check.status!=ExecutionStatus.COMPLETED or check.search_fingerprint!=model.search_fingerprint: continue
            if any(e.check_id==check.id and e.checker_id==result.invariant for e in self.state.evidence): continue
            claim=next(c for c in self.state.claims if c.id==result.claim_id)
            evidence=Evidence(check_id=check.id,model_id=model.id,snapshot_id=model.snapshot_id,claim_id=result.claim_id,
                search_fingerprint=check.search_fingerprint,origin=check.origin,level="framework_test" if self.state.mode=="mock" else "model",scope=result.scope,
                assessment=Assessment.INCONCLUSIVE if self.state.mode=="mock" else Assessment.SUPPORTED if result.outcome=="holds" else Assessment.CHALLENGED,
                calibration_id=calibration.id if calibration else None,checker_id=result.invariant,claim_version=claim.version,
                description="Candidate property in its explicit scope; applicability unresolved: "+str(claim.grounding.unresolved+claim.grounding.conflicts)+"; calibration="+(calibration.status if calibration else "not_scheduled"))
            self.state.add_evidence(evidence)
            self.state.relations.append(Relation(source=evidence.id,target=claim.id,kind="supports" if result.outcome=="holds" else "challenges",rationale="Direct scoped checker evidence; no graph proof propagation"))
            if result.outcome=="violated":
                self.state.findings.append(Finding(claim_id=claim.id,model_id=model.id,check_id=check.id,checker_id=result.invariant,
                    claim_version=claim.version,origin=check.origin,trace_path=check.stdout,
                    description="Violation of a candidate scoped checker; implementation applicability and execution remain to be established"))
        self.checkpoint("model_search_recorded")
        return check

    def graph_commit_hook(self,key):
        """Interruption seam after semantic manifest, before state checkpoint."""

    def check_triggers(self,model,bundle):
        from .modeling import check_triggers
        return check_triggers(self,model,bundle)
