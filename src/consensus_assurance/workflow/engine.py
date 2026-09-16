from .artifacts import load_model
import json
import math
import shutil
import time
from pathlib import Path
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Discovery, Bundle, Feedback, GraphPatch, ReplayPlan, BuildReply
from consensus_assurance.core.types import (Analysis, Assessment, Calibration, CheckRun, Evidence, ExecutionStatus,
    Finding, Investigation, Origin, Relation, Scope, uid, PendingAction, Record, Capability)
from consensus_assurance.ports.interfaces import AgentBackend, ImplementationAdapter, VerifierBackend
from . import discovery, inquiry
from consensus_assurance.adapters.runners.process import ProcessRunner, output
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events, prerequisites
from consensus_assurance.adapters.storage.files import Store, write_json, digest
from consensus_assurance.adapters.storage.snapshot import capture
from .graph import apply_discovery, select_unit, apply_patch
from .artifacts import save_bundle, validate_bundle
from .modeling import validate_build_reply, obligation_progress, coverage_limitations
from .investigation import feedback_context, validate_feedback, validate_replay, consequence_needed, validate_consequence, record_consequence
from .budget import BudgetTracker, BudgetExhausted
from .feedback import apply_feedback


from .errors import Blocked
from .agent_tasks import ask as ask_agent


FRAMEWORK_REVISION = "worksets-v1"


class Engine:
    def __init__(self, config: Config, root: Path, implementation: ImplementationAdapter,
                 agent: AgentBackend, verifier: VerifierBackend, knowledge: str, inquiry: str):
        self.config, self.root = config, root.resolve()
        self.implementation, self.agent, self.verifier = implementation, agent, verifier
        self.knowledge, self.inquiry = knowledge, inquiry
        self.store = Store(self.root)
        self.runner = ProcessRunner(self.root)
        self.state = None

    def checkpoint(self, event):
        self.budget.sync()
        from consensus_assurance.core.types import now
        observed={
            'initial_graph':'discovery' in self.state.completed_steps,
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
        write_json(self.root / "graph.json", {"version": self.state.graph_version,
            "claims": [x.model_dump(mode="json") for x in self.state.claims],
            "bindings": [x.model_dump(mode="json") for x in self.state.bindings],
            "relations": [x.model_dump(mode="json") for x in self.state.relations]})
        write_json(self.root / "plan.json", {"units": [u.model_dump(mode="json") for u in self.state.units], "selections": self.state.selections})

    def start(self, repo, plan_only=False):
        if self.root.is_relative_to(repo.resolve()) or repo.resolve().is_relative_to(self.root):
            raise ValueError("Run and original target directories must be disjoint")
        if not self.implementation.identify(repo):
            raise ValueError("Repository does not match the configured implementation adapter")
        started = time.monotonic()
        snapshot = capture(repo, self.root / "source")
        missing = [f for f in self.implementation.required_inputs(repo) if f not in snapshot.files] if hasattr(self.implementation,"required_inputs") else []
        if missing: raise ValueError("Required build inputs could not be safely copied: " + ", ".join(missing))
        self.state = Analysis(framework_revision=FRAMEWORK_REVISION, mode="mock" if self.agent.mock else "real", config=self.config.model_dump(mode="json"), snapshot=snapshot)
        self.state.guidance = [{"source":"consensus/inquiry.py","text":self.inquiry}, {"source":"configured_reference","text":self.knowledge}]
        self.state.analysis_mode = "regression" if self.agent.mock else ("directed" if self.config.directed_question else "autonomous")
        self.state.elapsed_seconds = time.monotonic() - started
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        write_json(self.root / "config.json", self.config)
        write_json(self.root / "snapshot.json", snapshot)
        self.checkpoint("created")
        return self.execute(plan_only=plan_only)

    def resume(self, action_timeout=None, repair_attempts=None):
        if repair_attempts is not None and (not isinstance(repair_attempts,int) or repair_attempts<0):raise ValueError("Repair attempt limit must be a nonnegative integer")
        if action_timeout is not None and (not math.isfinite(action_timeout) or action_timeout <= 0):
            raise ValueError("Action timeout must be a finite positive number")
        self.state = self.store.load()
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        if self.state.framework_revision!=FRAMEWORK_REVISION:
            self.state.stop_reason="Framework revision differs or was not recorded; preserve this historical run and use an explicit offline migration/subrun"
            return self.state
        current = capture(Path(self.state.snapshot.repo))
        reasons = []
        changed_models = set()
        if current.files != self.state.snapshot.files:
            reasons.append("Source snapshot changed")
        if self.config.model_dump(mode="json") != self.state.config:
            reasons.append("Configuration changed")
        for model in self.state.models:
            for path, expected in model.artifact_digests.items():
                if not Path(path).is_file() or digest(Path(path).read_bytes()) != expected:
                    reasons.append("Model, checker, mapping or harness artifact changed")
                    changed_models.add(model.id)
                    break
        copied = capture(self.root / "source")
        if copied.files != self.state.snapshot.files:
            reasons.append("Preserved source copy changed")
        if reasons:
            if all(reason == "Model, checker, mapping or harness artifact changed" for reason in reasons):
                self.state.affect(changed_models, "; ".join(reasons))
            else:
                self.state.invalidate("; ".join(reasons))
            self.state.stop_reason = "Inputs changed; start a new run to avoid mixing evidence"
            self.checkpoint("resume_inputs_changed")
            return self.state
        if repair_attempts is not None and repair_attempts!=self.config.budget.repair_attempts:
            old=self.config.budget.repair_attempts
            self.checkpoint("before_explicit_repair_budget_change")
            data=self.config.model_dump(mode="json");data['budget']['repair_attempts']=repair_attempts
            self.config=Config.model_validate(data);self.state.config=self.config.model_dump(mode='json');self.budget.limits=self.config.budget
            self.checkpoint(f"repair_attempt_limit_changed:{old}:{repair_attempts}; usage and failures preserved")
        if action_timeout is not None and action_timeout != self.config.budget.action_timeout:
            old_timeout = self.config.budget.action_timeout
            self.checkpoint("before_resume_timeout_adjustment")
            data = self.config.model_dump(mode="json")
            data["budget"]["action_timeout"] = action_timeout
            self.config = Config.model_validate(data)
            self.state.config = self.config.model_dump(mode="json")
            self.budget.limits = self.config.budget
            self.checkpoint(f"resume_action_timeout_changed:{old_timeout}:{action_timeout}")
        if self.agent.mock:
            completed_agent_results = list((self.root / "actions").glob("*/result.json"))
            self.agent.cursor = sum(1 for path in completed_agent_results
                if isinstance(value := json.loads(path.read_text()), list) and value and isinstance(value[0], dict)
                and value[0].get("action") == "agent")
        old_tools = dict(self.state.tools)
        historical_check_ids = {check.id for check in self.state.checks}
        self.probe_tools()
        if old_tools and old_tools != self.state.tools:
            self.state.invalidate("Tool versions or availability changed")
            self.state.stop_reason = "Tool inputs changed; start a new run for revalidation"
            self.checkpoint("resume_tools_changed")
            return self.state
        for check in self.state.checks:
            if check.id in historical_check_ids and check.status == ExecutionStatus.COMPLETED:
                check.reused = True
            if check.status == ExecutionStatus.RUNNING:
                check.status = ExecutionStatus.CANCELLED
                check.reason = "Previous controller stopped; execution outcome unknown"
        if self.state.pending_action and self.state.pending_action.status == "running":
            result = self.root / "actions" / self.state.pending_action.id / "result.json"
            if result.exists():
                self.state.pending_action.status = "completed"
            else:
                self.state.pending_action.status = "outcome_unknown"
                self.state.action_history.append(self.state.pending_action.model_copy(deep=True))
                self.state.gaps.append("Interrupted action outcome unknown; retry the same stage within budget in a fresh isolated execution")
                self.state.pending_action = None
        pending = self.state.pending_action
        if pending and pending.status == "completed" and pending.kind.startswith("agent:"):
            result_path = self.root / "actions" / pending.id / "result.json"
            payload = json.loads(result_path.read_text()) if result_path.exists() else None
            if isinstance(payload, list) and len(payload) == 2 and (
                payload[0].get("status") != ExecutionStatus.COMPLETED.value or payload[1] is None
            ):
                # The execution happened, but a rejected request is not a reusable response.
                self.state.action_history.append(pending.model_copy(deep=True))
                self.state.pending_action = None
                self.checkpoint("blocked_agent_request_scheduled_for_retry")
        if inquiry.enabled(self): inquiry.resume_deferred(self)
        self.checkpoint("resumed_history_reused_without_reexecution")
        return self.execute(probed=True)

    def record(self, check):
        if any(c.id == check.id for c in self.state.checks):
            return
        self.state.checks.append(check)
        self.checkpoint("execution_recorded")

    def probe_tools(self):
        for name, backend in [("agent", self.agent), ("verifier", self.verifier)]:
            self.budget.timeout()
            result = backend.probe(self.runner)
            self.state.tools[name] = result["version"]
            for check in result["checks"]:
                self.record(check)
                if check.action == "java_probe":
                    self.state.tools["java"] = output(check).strip()
            if not result["available"]:
                self.state.gaps.append(result["reason"])
        check = self.runner.run(self.implementation.version_command(), self.root, "implementation_tool_probe", self.state.snapshot.id, self.budget.timeout())
        self.record(check)
        self.state.tools["implementation"] = output(check).strip()

    def workspace(self):
        directory = self.root / "experiments" / uid() / "workspace"
        shutil.copytree(self.root / "source", directory)
        return directory

    def action(self, kind, resource, callback, inputs=None):
        pending = self.state.pending_action
        from .action_identity import stable_input
        logical={'inputs':stable_input(inputs or {}),'inquiry_id':self.state.active_inquiry_id,'finding_id':self.state.active_finding_id}
        if pending and pending.kind==kind and pending.unit_id==self.state.active_unit_id and pending.model_id==self.state.active_model_id and pending.finding_id==self.state.active_finding_id and pending.inquiry_id==self.state.active_inquiry_id:
            result_path=self.root/'actions'/pending.id/'result.json'
            original=Path(pending.input_path)
            if pending.status=='completed' and result_path.exists() and original.is_file() and pending.logical_input==logical and stable_input(json.loads(original.read_text()))==logical['inputs']:
                return json.loads(result_path.read_text())
        if pending:
            self.state.action_history.append(pending.model_copy(deep=True))
        self.budget.take(resource)
        action = PendingAction(inquiry_id=self.state.active_inquiry_id,logical_input=logical,kind=kind,unit_id=self.state.active_unit_id,model_id=self.state.active_model_id,finding_id=self.state.active_finding_id)
        directory = self.root / "actions" / action.id
        action.input_path = str(directory / "input.json")
        write_json(Path(action.input_path),inputs or {})
        self.state.pending_action = action
        self.checkpoint("action_planned")
        action.status = "running"; self.runner.active_action_id = action.id
        self.checkpoint("action_started")
        value = callback()
        def pack(item):
            if isinstance(item,Record): return item.model_dump(mode="json")
            if isinstance(item,(tuple,list)): return [pack(x) for x in item]
            if isinstance(item,dict): return {k:pack(v) for k,v in item.items()}
            return item
        value = pack(value)
        write_json(directory / "result.json",value)
        action.status = "completed"
        self.checkpoint("action_result_saved")
        return value

    def advance(self, stage):
        if self.state.pending_action:
            self.state.action_history.append(self.state.pending_action.model_copy(deep=True))
            self.state.pending_action = None
        self.state.next_action = stage
        self.checkpoint("next_action_" + stage)

    def error_context(self, check):
        raw = output(check)
        bound = self.config.budget.error_context_chars
        text = raw if len(raw)<=bound else raw[:bound//2] + "\n[OUTPUT TRUNCATED]\n" + raw[-bound//2:]
        return {"check_id":check.id,"status":check.status.value,"reason":check.reason,"text":text,
                "original_characters":len(raw),"truncated":len(raw)>bound,"stdout_path":check.stdout,"stderr_path":check.stderr}

    def ask(self, kind, response_type, context, validator=None):
        return ask_agent(self,kind,response_type,context,validator)

    def context(self, unit=None):
        return discovery.context(self,unit)

    def discover(self):
        return discovery.discover(self)

    def targeted_read(self, unit, gap, relation_ids=None, requests=None, update_required=True):
        return discovery.targeted_read(self,unit,gap,relation_ids,requests,update_required)

    def experiment(self, model, bundle, replay=False):
        if not self.config.allow_experiments:
            raise Blocked("Target execution disabled; capability probes and replay are also prohibited")
        def execute():
            if replay: self.budget.take("replays")
            workspace=self.workspace()
            destination=workspace/self.implementation.harness_filename
            if destination.exists(): raise Blocked("Generated harness would overwrite a target file")
            destination.write_text(bundle.harness.source)
            check=run_experiment(self.runner,self.implementation.experiment_command(),workspace,self.state.snapshot.id,
                self.budget.timeout(),self.config.execution_isolation,"replay" if replay else "experiment",adapter=self.implementation)
            check.model_id=model.id; check.input_versions=model.artifact_digests
            check.tool_version=self.state.tools.get("implementation","unknown")
            check.origin=Origin.MOCK if self.state.mode=="mock" else Origin.EXECUTED
            check.artifacts=[str(destination),model.mapping_path]
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

    def save_model(self, unit, bundle, previous=None, reason="Initial generation"):
        key = self.state.pending_action.id if self.state.pending_action else None
        if key is None:
            raise Blocked("Model commit requires a persisted generation action")
        model = save_bundle(self.root, self.state, unit, bundle, self.implementation, previous, reason, transaction_key=key)
        self.model_commit_hook(model)
        if previous and bundle.properties!=load_model(previous).properties and "Encoding" in reason:
            from consensus_assurance.core.types import ReviewIssue
            if not any(i.model_id==model.id and i.needs_recheck for i in self.state.review_issues):
                sources=sorted({s for c in self.state.claims if c.id in {spec.claim_id for spec in model.checkers} for s in c.source_ids})
                self.state.review_issues.append(ReviewIssue(review_id="encoding:"+model.id,target_id=model.id,target_version=model.version,aspect="checker_correspondence",model_id=model.id,source_ids=sources,explanation=reason,disposition="revision",reason="The new encoding needs actual rechecking and correspondence review",needs_recheck=True))
        from .inputs import reusable_search
        source=reusable_search(self.state,model)
        if source:
            receipt=source.model_copy(deep=True)
            receipt.id=uid();receipt.model_id=model.id;receipt.reused=True;receipt.reused_from=source.id
            receipt.input_versions=model.artifact_digests
            receipt.reason="Explicit reuse of identical search inputs from "+source.id
            self.record(receipt)
        return model

    def read_commit_hook(self,stage,receipt):
        """Interruption seam around the atomic material receipt commit."""

    def read(self,requests,**kwargs):
        from .materials import execute_read
        return execute_read(self,requests,**kwargs)

    def graph_commit_hook(self,key):
        """Interruption seam after semantic manifest, before state checkpoint."""

    def commit_feedback(self,unit,bundle,feedback):
        from .transactions import commit_graph
        check_id=self.state.pending_action.id if self.state.pending_action else feedback.evidence_ids[0]
        key="feedback-"+check_id+"-"+feedback.kind+"-"+unit.id
        def apply(proxy):
            target=next(u for u in proxy.state.units if u.id==unit.id)
            apply_feedback(proxy.state,target,bundle,feedback)
            if feedback.kind=="F2" and proxy.state.revisions[-1].status=="applied":
                proxy.state.active_model_id=None;proxy.state.active_finding_id=None;proxy.state.next_action="build"
                inquiry.release_action(proxy)
            elif feedback.kind=="F3":
                proxy.state.active_unit_id=None;proxy.state.active_model_id=None;proxy.state.active_finding_id=None;proxy.state.next_action="select"
                inquiry.release_action(proxy)
        commit_graph(self,key,feedback.model_dump(mode="json"),apply)
        if feedback.kind in {"F1","F4"}:return feedback.bundle
        if feedback.kind=="F3":return next((u for u in self.state.units if u.previous_id==unit.id and u.status=="pending"),None)

    def model_commit_hook(self, model):
        """Interruption test seam after durable model files, before state registration."""

    def check_triggers(self,model,bundle):
        from .modeling import check_triggers
        return check_triggers(self,model,bundle)

    def finish_unit(self, unit, status="checked"):
        unit.coverage_limitations=coverage_limitations(self.state,unit)
        old = set(unit.obligation_checks)
        unit.obligation_checks, unit.remaining_obligation_ids = obligation_progress(self.state, unit)
        if status == "checked" and unit.remaining_obligation_ids:
            status = "partial" if set(unit.obligation_checks) != old else "blocked"
            self.state.gaps.append("Unfinished obligations in " + unit.id + ": " + ", ".join(unit.remaining_obligation_ids))
        unit.status=status
        if status=="checked":self.state.deferred_units.pop(unit.id,None)
        self.state.active_unit_id=None; self.state.active_model_id=None; self.state.active_finding_id=None
        self.advance("select")

    def process_unit(self, unit):
        from .observations import assess_execution
        self.state.active_unit_id=unit.id
        if self.state.next_action=="select": self.advance("build")
        while self.state.active_unit_id:
            unit=next(u for u in self.state.units if u.id==self.state.active_unit_id)
            phase=self.state.next_action
            model=next((m for m in self.state.models if m.id==self.state.active_model_id),None)
            bundle=load_model(model) if model else None
            experiment=next((c for c in reversed(self.state.checks) if model and c.model_id==model.id and c.action in {"experiment","replay"}),None)
            calibration=next((c for c in reversed(self.state.calibrations) if experiment and c.experiment_check_id==experiment.id),None)
            finding=next((f for f in self.state.findings if f.id==self.state.active_finding_id),None)
            if phase in {"model_syntax", "model_explore", "model_repair", "harness"}:
                from .staged_model import proceed
                proceed(self, unit, model, bundle, phase)
                continue
            if phase=="build":
                if self.state.targeted_gap:
                    task=self.state.targeted_gap
                    self.targeted_read(unit,task["gap"],task.get("relation_ids"),task.get("requests"))
                    self.advance("build");continue
                if not inquiry.prepare_selected(self,unit):return
                previous=model or next((m for m in reversed(self.state.models) if m.unit_id==unit.previous_id),None)
                if previous is None and (unit.recheck_reasons or unit.obligation_checks):
                    previous=next((m for m in reversed(self.state.models) if m.unit_id==unit.id),None)
                context=self.context(unit)
                if previous:
                    context.update(previous_bundle=json.loads(Path(previous.bundle_path).read_text()),scope_delta={"before":previous.scope.model_dump(),"after":unit.scope.model_dump(),"added_bindings":list(set(unit.binding_ids)-set(previous.binding_ids)),"boundary_changes":unit.boundary_changes})
                reply,_=self.ask("F3" if unit.previous_id else "build",BuildReply,context, lambda p: validate_build_reply(self.state,unit,p,self.implementation))
                if reply.bundle is None and reply.draft is None:
                    self.targeted_read(unit,reply.gap,requests=reply.requests,update_required=reply.reading_purpose=="dependency"); self.advance("build"); continue
                if reply.draft is not None:
                    model=self.save_model(unit,reply.draft,previous,"Staged local model; implementation experiment pending")
                    self.state.active_model_id=model.id
                    if self.state.first_model_seconds is None:self.budget.sync();self.state.first_model_seconds=self.state.elapsed_seconds
                    self.advance("model_syntax")
                    continue
                if previous:
                    original=load_model(previous)
                    if reply.bundle.properties!=original.properties and reply.bundle.checker_specs()==original.checker_specs() and reply.bundle.scope==original.scope and all(previous.graph_versions.get(c.id)==c.version for c in self.state.claims if c.id in previous.graph_versions):
                        if not reply.encoding_revision:raise Blocked("Changed checker encoding needs an attributed encoding_revision and correspondence review")
                        from .encoding import validate_encoding
                        validate_encoding(self.state,previous,original,reply.bundle,reply.encoding_revision)
                model=self.save_model(unit,reply.bundle,previous,"Encoding correction: "+reply.encoding_revision.rationale if reply.encoding_revision else "Continued scoped investigation after feedback" if previous else "Initial generation")
                self.state.active_model_id=model.id
                if self.state.first_model_seconds is None: self.budget.sync(); self.state.first_model_seconds=self.state.elapsed_seconds
                self.advance("experiment" if self.config.allow_experiments else "search")
                if inquiry.enabled(self): return
            elif phase in {"experiment","replay"}:
                if not self.config.allow_experiments: raise Blocked("Target execution disabled")
                experiment=self.experiment(model,bundle,replay=phase=="replay")
                if experiment.status!=ExecutionStatus.COMPLETED or experiment.outcome not in {"tests_passed","tests_failed"}:
                    if experiment.status==ExecutionStatus.ERROR:
                        self.state.pending_feedback={"technical_phase":phase,"check_id":experiment.id}
                        self.advance("technical_repair"); continue
                    raise Blocked("Experiment execution did not complete: "+experiment.status.value)
                self.advance("replay_calibrate" if phase=="replay" else "calibrate")
            elif phase in {"calibrate","replay_calibrate"}:
                calibration=self.calibrate(model,bundle,experiment)
                if calibration.status=="incompatible":
                    self.state.pending_feedback={"return_after_repair":"replay" if phase=="replay_calibrate" else "experiment"}
                    self.advance("feedback_F1")
                else:
                    if calibration.status!="compatible":
                        self.state.gaps.append("Calibration remains "+calibration.status+" for model "+model.id+"; subsequent search is exploratory")
                        inquiry.review_unit(self,unit,"calibration_unresolved:"+calibration.id,model)
                    self.advance("assess" if phase=="replay_calibrate" else "search")
            elif phase=="search":
                check=self.search(unit,model,bundle,calibration)
                if check.status!=ExecutionStatus.COMPLETED:
                    if check.reason=="Model syntax error":
                        self.state.pending_feedback={"technical_phase":"search","check_id":check.id}; self.advance("technical_repair"); continue
                    raise Blocked("Search did not complete: "+check.status.value)
                if check.outcome=="deadlock":
                    raise Blocked("Model deadlock diagnosis; invariant searches remain incomplete")
                failed=next((f for f in reversed(self.state.findings) if f.check_id==check.id),None)
                if check.outcome=="counterexample" and not failed:
                    raise Blocked("Reported invariant cannot be attributed to a configured claim; other properties remain unknown")
                inquiry.after_search(self,unit,model,check)
                self.state.last_work_kind="local"
                if failed:
                    self.state.active_finding_id=failed.id; failed.stage=Investigation.REACHABILITY_PENDING
                    self.advance("replay_plan")
                else:
                    self.advance("triggers")
                if inquiry.enabled(self): return
            elif phase=="triggers":
                self.check_triggers(model,bundle)
                self.advance("expand")
            elif phase=="expand":
                dependencies=[e for e in self.state.relations if e.source in unit.obligation_ids and e.kind=="boundary" and e.target not in unit.obligation_ids+unit.binding_ids and not any(e.target in {a.claim_id for a in b.associations} for b in self.state.bindings if b.id in unit.binding_ids)]
                if not dependencies:
                    unreviewed=[r for r in self.state.relations if r.source in unit.obligation_ids and r.kind in {"boundary","conditional_on"} and (r.pending or r.grounding.unresolved)]
                    if unreviewed:
                        inquiry.review_unit(self,unit,"in_scope_guarantee")
                        self.state.gaps.append("Included bindings do not establish boundary guarantees; use scoped review or F1 action-granularity refinement: "+", ".join(r.id for r in unreviewed))
                    self.finish_unit(unit);return
                edge=dependencies[0]
                if not any(b.id==edge.target or any(a.claim_id==edge.target for a in b.associations) for b in self.state.bindings):
                    self.targeted_read(unit,edge.rationale,[edge.id])
                    edge=next(e for e in self.state.relations if e.id==edge.id)
                self.budget.take("revisions")
                check=next(c for c in reversed(self.state.checks) if c.action=="model_check" and c.model_id==model.id)
                f=Feedback(kind="F3",rationale="Explain the unresolved boundary through its actual producer",evidence_ids=[check.id],target_ids=[unit.id],relation_ids=[edge.id],new_basis="",graph=None,bundle=None)
                self.commit_feedback(unit,bundle,f)
                self.state.active_unit_id=None; self.state.active_model_id=None; self.advance("select"); return
            elif phase=="replay_plan":
                if not self.config.allow_experiments: raise Blocked("Candidate replay disabled by experiment permission")
                search=next(c for c in self.state.checks if c.id==finding.check_id)
                plan,_=self.ask("replay",ReplayPlan,{**self.context(unit),"bundle":bundle.model_dump(mode="json"),"finding":finding.model_dump(mode="json"),"candidate_trace":self.error_context(search)}, lambda p: validate_replay(self.state,unit,bundle,finding,p,self.implementation))
                revised=validate_replay(self.state,unit,bundle,finding,plan,self.implementation)
                new=self.save_model(unit,revised,model,"Initial candidate experiment and observation plan; not F4")
                self.state.active_model_id=new.id; self.advance("replay")
            elif phase=="assess":
                record=assess_execution(self.state,model,bundle,experiment,calibration,finding,extract_events(experiment))
                path=self.root/"findings"/finding.id/(experiment.id+".json"); write_json(path,record); finding.confirmation_path=str(path)
                if record["confirmed"]:
                    if consequence_needed(unit,finding):self.advance("consequence_plan");continue
                    self.finish_unit(unit);return
                if record["prerequisites"]["status"]=="not_reached": self.advance("feedback_F4")
                else: self.advance("diagnose")
            elif phase=="consequence_plan":
                from consensus_assurance.core.proposals import ConsequenceReply
                from .transactions import commit_graph
                if any(c['finding_id']==finding.id for c in self.state.consequences):
                    self.finish_unit(unit);return
                try:
                    if not self.state.pending_action or not self.state.pending_action.kind.startswith("agent:consequence"):
                        self.budget.take("consequence_investigations")
                    reply,check=self.ask("consequence",ConsequenceReply,{**self.context(unit),"finding":finding.model_dump(mode="json"),"assessment":next((r for r in reversed(self.state.monitor_results) if r['finding_id']==finding.id),None)},lambda p:validate_consequence(self.state,unit,p))
                    commit_graph(self,"consequence-"+check.id,reply.model_dump(mode="json"),lambda proxy:record_consequence(proxy,unit,finding,reply))
                except (BudgetExhausted,Blocked,ValueError) as exc:
                    record_consequence(self,unit,finding,reason=str(exc))
                self.finish_unit(unit);return
            elif phase in {"feedback_F1","feedback_F4","diagnose"}:
                kind=phase.removeprefix("feedback_")
                context=feedback_context(self,unit,model,bundle,experiment,calibration,finding)
                f,_=self.ask(kind,Feedback,context,lambda p:validate_feedback(self.state,unit,bundle,p,self.implementation,kind))
                if f.requests:
                    self.targeted_read(unit,f.rationale,requests=f.requests); self.advance(phase); continue
                if f.kind=="unresolved":
                    self.state.gaps.append(f.rationale); self.finish_unit(unit,"blocked"); return
                if kind in {"F1","F4"} and f.kind!=kind: raise Blocked("Feedback attempts to change a different semantic object")
                self.budget.take("revisions")
                old_version=self.state.graph_version
                updated=self.commit_feedback(unit,bundle,f)
                if f.kind=="F2":
                    if old_version==self.state.graph_version: self.finish_unit(unit,"blocked"); return
                    self.state.active_model_id=None; self.state.active_finding_id=None; self.advance("build")
                elif f.kind=="F3":
                    self.state.active_unit_id=None; self.state.active_model_id=None; self.advance("select"); return
                elif updated:
                    new=self.save_model(unit,updated,model,f.kind+" revision")
                    self.state.active_model_id=new.id
                    self.advance("replay" if f.kind=="F4" or finding else "experiment")
                else: self.finish_unit(unit,"blocked"); return
            elif phase=="technical_repair":
                if not self.state.pending_action or not self.state.pending_action.kind.startswith("agent:technical"):
                    self.budget.take("technical_repairs")
                failure=next(c for c in self.state.checks if c.id==self.state.pending_feedback["check_id"])
                reply,_=self.ask("technical",BuildReply,{**self.context(unit),"model_id":model.id,"semantic_versions":model.graph_versions,"bundle":bundle.model_dump(mode="json"),"failure":self.error_context(failure)}, lambda p: validate_build_reply(self.state,unit,p,self.implementation,bundle,self.state.pending_feedback["technical_phase"]))
                if reply.bundle is None:
                    self.targeted_read(unit,reply.gap,requests=reply.requests,update_required=reply.reading_purpose=="dependency"); self.advance("technical_repair"); continue
                repaired=reply.bundle
                new=self.save_model(unit,repaired,model,"Encoding correction: "+reply.encoding_revision.rationale if reply.encoding_revision else "Bounded technical repair; no semantic attribution")
                self.state.active_model_id=new.id
                self.advance("replay" if finding else "experiment" if self.config.allow_experiments else "search")
            else: raise Blocked("Unknown checkpoint action: "+phase)

    def execute(self, probed=False, plan_only=False):
        try:
            if not probed:
                self.probe_tools()
            if "capabilities" not in self.state.completed_steps:
                if self.config.allow_experiments:
                    def probe():
                        workspace=self.workspace()
                        check=run_experiment(self.runner,self.implementation.probe_command(),workspace,self.state.snapshot.id,
                            self.budget.timeout(),self.config.execution_isolation,"capability_probe",adapter=self.implementation)
                        check.tool_version=self.state.tools.get("implementation","unknown")
                        return check
                    check=CheckRun.model_validate(self.action("capability_probe","experiments",probe))
                    self.record(check); self.state.capabilities=self.implementation.capabilities(check)
                else:
                    self.state.capabilities=[Capability(name="target_execution",status="unavailable",check_id=None,description="All target execution, including probes and replay, disabled by configuration")]
                self.state.completed_steps.append("capabilities"); self.advance("discover")
            self.discover()
            if plan_only:
                self.state.stop_reason = "Plan generated; modeling and checks not scheduled"
                return self.state
            while True:
                inquiry.wake_changed(self)
                inquiry.clear_reserve(self)
                can_inquire = inquiry.enabled(self) and (self.state.active_inquiry_id or (self.state.pending_action is None and self.state.pending_output_repair is None))
                if can_inquire:
                    if not self.state.active_unit_id and self.state.usage.get("audit_units",0)<self.config.budget.audit_units:
                        candidate=select_unit(self.state)
                        if candidate:
                            self.budget.take("audit_units");self.state.active_unit_id=candidate.id;self.state.next_action="build"
                            self.checkpoint("actual_unit_selected_before_review")
                    candidate=next((u for u in self.state.units if u.id==self.state.active_unit_id),None)
                    if candidate and self.state.next_action in {"select","build"}:
                        inquiry.review_unit(self,candidate,"before_model")
                    task=inquiry.choose_task(self)
                    if task:
                        try:
                            inquiry.process_task(self,task)
                        except (BudgetExhausted,Blocked,ValueError,OSError) as exc:
                            task.status="blocked";task.stop_reason=str(exc)
                            current_task=next(t for t in self.state.inquiry_tasks if t.id==task.id)
                            current_task.repair_session=self.state.pending_output_repair
                            self.state.active_inquiry_id=None;self.state.pending_output_repair=None
                            inquiry.release_action(self);self.state.gaps.append(str(exc))
                            self.checkpoint("inquiry_task_blocked")
                            if str(exc).startswith("Agent blocked:"): raise
                        continue
                if self.state.active_unit_id:
                    active=next(u for u in self.state.units if u.id==self.state.active_unit_id)
                    if inquiry.enabled(self): inquiry.reserve_for_inquiry(self)
                    try:
                        self.process_unit(active)
                    except (BudgetExhausted,Blocked,ValueError,OSError) as exc:
                        if not inquiry.enabled(self) or str(exc).startswith("Agent blocked:"): raise
                        inquiry.pause_unit(self,str(exc))
                    continue
                if not any(u.status in {"pending", "partial"} for u in self.state.units):
                    missing = [u.id + ": " + ", ".join(u.remaining_obligation_ids) for u in self.state.units if u.remaining_obligation_ids and u.status != "revised"]
                    self.state.stop_reason = "Unfinished obligations remain without an executable next step: " + "; ".join(missing) if missing else "No pending executable audit units; unresolved gaps remain"
                    if inquiry.enabled(self) and any(t.status in {"blocked","pending","running"} for t in self.state.inquiry_tasks):
                        self.state.stop_reason="Inquiry work remains incomplete; exploration or review is blocked by budget, evidence or capability"
                    elif inquiry.enabled(self) and any(u.status=="blocked" for u in self.state.units):
                        self.state.stop_reason="Local audit work remains blocked; inspect remaining obligations and deferred actions"
                    break
                if self.state.usage.get("audit_units", 0) >= self.config.budget.audit_units:
                    if inquiry.enabled(self):
                        for candidate in self.state.units:
                            if candidate.status in {"pending","partial"}:
                                candidate.status="blocked";candidate.recheck_reasons.append("Audit-unit budget exhausted")
                                candidate.obligation_checks,candidate.remaining_obligation_ids=obligation_progress(self.state,candidate)
                        self.state.last_work_kind="local"
                        continue
                    raise BudgetExhausted("Audit-unit budget exhausted")
                unit = select_unit(self.state)
                if unit is None:
                    self.state.stop_reason = "No pending executable audit units; unresolved gaps remain"
                    break
                self.budget.take("audit_units"); self.state.active_unit_id=unit.id; self.checkpoint("relation_driven_selection")
                if inquiry.enabled(self):
                    self.state.next_action="select"
                    self.state.last_work_kind="local"
                    continue
                self.process_unit(unit)
        except (BudgetExhausted, Blocked, ValueError, OSError) as exc:
            self.state.stop_reason = str(exc)
            self.state.gaps.append(str(exc))
        finally:
            self.checkpoint("stopped")
        return self.state
