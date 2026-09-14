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
from .prompts import render
from consensus_assurance.adapters.runners.process import ProcessRunner, output
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events, prerequisites
from consensus_assurance.adapters.storage.files import Store, write_json, digest
from consensus_assurance.adapters.storage.snapshot import capture
from .materials import catalogue, initial_materials, add_reads, ReadingPlan
from .graph import apply_discovery, select_unit, apply_patch
from .artifacts import save_bundle
from .budget import BudgetTracker, BudgetExhausted
from .feedback import apply_feedback


class Blocked(RuntimeError):
    pass


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
        self.state = Analysis(mode="mock" if self.agent.mock else "real", config=self.config.model_dump(mode="json"), snapshot=snapshot)
        self.state.guidance = [{"source":"consensus/inquiry.py","text":self.inquiry}, {"source":"configured_reference","text":self.knowledge}]
        self.state.analysis_mode = "regression" if self.agent.mock else ("directed" if self.config.directed_question else "autonomous")
        self.state.elapsed_seconds = time.monotonic() - started
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        write_json(self.root / "config.json", self.config)
        write_json(self.root / "snapshot.json", snapshot)
        self.checkpoint("created")
        return self.execute(plan_only=plan_only)

    def resume(self, action_timeout=None):
        if action_timeout is not None and (not math.isfinite(action_timeout) or action_timeout <= 0):
            raise ValueError("Action timeout must be a finite positive number")
        self.state = self.store.load()
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
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
        if pending and pending.kind == kind and pending.unit_id == self.state.active_unit_id and pending.model_id == self.state.active_model_id:
            result_path = self.root / "actions" / pending.id / "result.json"
            if pending.status == "completed" and result_path.exists():
                return json.loads(result_path.read_text())
        if pending:
            self.state.action_history.append(pending.model_copy(deep=True))
        self.budget.take(resource)
        action = PendingAction(kind=kind,unit_id=self.state.active_unit_id,model_id=self.state.active_model_id,finding_id=self.state.active_finding_id)
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
        if not self.agent.mock and not self.config.allow_agent_materials:
            raise Blocked("Agent material transmission disabled by configuration; no repository payload was sent")
        original = kind
        last_error = "Unknown validation error"
        for attempt in range(self.config.budget.repeated_error_revisions + 1):
            directory = self.root / "agent" / (uid()+"-"+original)
            prompt = render(kind,context,self.inquiry if original in {"read","discover","F3","targeted_read","graph_patch"} else "")
            payload = self.action("agent:"+original,"agent_calls",
                lambda:self.agent.analyze(self.runner,prompt,directory,self.state.snapshot.id,self.budget.timeout(),response_type),
                {"prompt":prompt,"response_type":response_type.__name__})
            check = CheckRun.model_validate(payload[0])
            response = response_type.model_validate(payload[1]) if payload[1] is not None else None
            self.record(check)
            if response is not None:
                try:
                    if validator: validator(response)
                    return response,check
                except ValueError as exc:
                    last_error = str(exc)
                    (Path(check.cwd) / "graph-validation-error.txt").write_text(last_error)
                    context={"task":original,"previous_response":response.model_dump(mode="json"),"validation_error":str(exc),"original_context":context}
            elif check.reason == "Structured agent output is invalid":
                raw_path = Path(check.cwd)/"raw-response.txt"
                error_path = Path(check.cwd)/"validation-error.txt"
                context={"task":original,"validation_error":error_path.read_text() if error_path.exists() else check.reason,
                    "raw_output":raw_path.read_text()[:self.config.budget.error_context_chars] if raw_path.exists() else "", "original_context":context}
            else:
                raise Blocked(f"Agent blocked: {check.status.value}; {check.reason}")
            last_error = context.get("validation_error", last_error)
            if self.state.pending_action:
                self.state.action_history.append(self.state.pending_action.model_copy(deep=True)); self.state.pending_action=None
            kind="retry"
        raise Blocked("Structured response repair limit reached: " + last_error)

    def context(self, unit=None):
        result = {"materials": [m.model_dump(mode="json") for m in self.state.materials],
            "capabilities": [c.model_dump(mode="json") for c in self.state.capabilities],
            "parameters": self.config.parameters, "remaining_seconds": self.budget.remaining(),
            "directed_question": self.config.directed_question,
            "snapshot_id": self.state.snapshot.id, "harness_kind": self.implementation.harness_kind,
            "harness_instructions": self.implementation.harness_instructions}
        if unit:
            ids = {b.file for b in self.state.bindings if b.id in unit.binding_ids}
            ids |= {m.file for m in self.state.materials if any(m.id in c.source_ids for c in self.state.claims if c.id in unit.goal_ids+unit.obligation_ids)}
            recent = set(self.state.reading_history[-1]["added_material_ids"]) if self.state.reading_history else set()
            result["materials"] = [m.model_dump(mode="json") for m in self.state.materials if m.file in ids or m.id in recent]
            result.update({"unit": unit.model_dump(mode="json"), "claims": [c.model_dump(mode="json") for c in self.state.claims],
                "bindings": [b.model_dump(mode="json") for b in self.state.bindings if b.id in unit.binding_ids],
                "relations": [e.model_dump(mode="json") for e in self.state.relations]})
        return result

    def discover(self):
        source = self.root / "source"
        if "materials" not in self.state.completed_steps:
            self.state.materials = initial_materials(source, self.state.snapshot, self.config.budget, self.knowledge)
            inventory = catalogue(source, self.state.snapshot,self.implementation)
            write_json(self.root / "catalogue.json", inventory)
            plan, _ = self.ask("read", ReadingPlan, {"catalogue": inventory, "initial_materials": [m.model_dump(mode="json") for m in self.state.materials]})
            add_reads(self.state, source, plan, self.config.budget)
            write_json(self.root / "materials.json", [m.model_dump(mode="json") for m in self.state.materials])
            self.state.completed_steps.append("materials"); self.advance("discover")
        if "discovery" not in self.state.completed_steps:
            proposal, check = self.ask("discover", Discovery, self.context(), lambda p: apply_discovery(self.state, p))
            path = self.root / f"discovery-v{self.state.graph_version}.json"
            write_json(path, proposal); self.state.discovery_path = str(path)
            if not self.state.units and proposal.reading_requests:
                self.targeted_read(None, "Insufficient material for grounded discovery", requests=proposal.reading_requests)
            self.state.completed_steps.append("discovery"); self.advance("select")

    def targeted_read(self, unit, gap, relation_ids=None, requests=None):
        source = self.root/"source"
        if self.state.targeted_gap is None:
            self.budget.take("targeted_reads")
            self.state.targeted_gap={"gap":gap,"related_ids":unit.obligation_ids if unit else [],
                "relation_ids":relation_ids or [],"stage":"read","new_material_ids":[]}
            self.checkpoint("targeted_gap_recorded")
        task=self.state.targeted_gap
        if task["stage"] == "read":
            if requests:
                reading=ReadingPlan.model_validate({"requests":requests,"rationale":gap,"related_ids":task["related_ids"],"gap":gap})
            else:
                reading,_=self.ask("targeted_read",ReadingPlan,{"gap":task,"catalogue":catalogue(source,self.state.snapshot,self.implementation),
                    "already_read":[{"id":m.id,"file":m.file,"start":m.start_line,"end":m.end_line} for m in self.state.materials],
                    "relevant_bindings":[b.model_dump() for b in self.state.bindings if unit and b.id in unit.binding_ids]})
            reading.related_ids=task["related_ids"]; reading.gap=gap
            task["new_material_ids"]=add_reads(self.state,source,reading,self.config.budget)
            task["stage"]="patch"
            if self.state.pending_action: self.state.action_history.append(self.state.pending_action); self.state.pending_action=None
            self.checkpoint("targeted_materials_read")
        if not task["new_material_ids"]:
            self.state.targeted_gap=None
            raise Blocked("Targeted reading found no new usable range; dependency remains unexplained: " + gap)
        patch,_=self.ask("graph_patch",GraphPatch,{"gap":task,
            "new_materials":[m.model_dump(mode="json") for m in self.state.materials if m.id in task["new_material_ids"]],
            "claims":[c.model_dump(mode="json") for c in self.state.claims],"bindings":[b.model_dump(mode="json") for b in self.state.bindings],
            "relations":[e.model_dump(mode="json") for e in self.state.relations if e.source in {c.id for c in self.state.claims}],
            "units":[u.model_dump(mode="json") for u in self.state.units]},lambda p:apply_patch(self.state,p))
        write_json(self.root/"materials.json",[m.model_dump(mode="json") for m in self.state.materials])
        self.state.targeted_gap=None
        if self.state.pending_action: self.state.action_history.append(self.state.pending_action); self.state.pending_action=None
        self.checkpoint("targeted_graph_patch_applied")
        return patch

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
        check=CheckRun.model_validate(self.action("model_search","model_checks",lambda:self.verifier.check(self.runner,model,self.budget.timeout()),{"model_id":model.id}))
        check.origin=Origin.MOCK if self.state.mode=="mock" else Origin.EXECUTED
        self.record(check)
        for result in check.checker_results:
            if result.outcome=="unknown" or check.status!=ExecutionStatus.COMPLETED: continue
            if any(e.check_id==check.id and e.checker_id==result.invariant for e in self.state.evidence): continue
            claim=next(c for c in self.state.claims if c.id==result.claim_id)
            evidence=Evidence(check_id=check.id,model_id=model.id,snapshot_id=model.snapshot_id,claim_id=result.claim_id,
                origin=check.origin,level="framework_test" if self.state.mode=="mock" else "model",scope=result.scope,
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

    def finish_unit(self, unit, status="checked"):
        unit.status=status
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
            bundle=Bundle.model_validate_json(Path(model.bundle_path).read_text()) if model else None
            experiment=next((c for c in reversed(self.state.checks) if model and c.model_id==model.id and c.action in {"experiment","replay"}),None)
            calibration=next((c for c in reversed(self.state.calibrations) if experiment and c.experiment_check_id==experiment.id),None)
            finding=next((f for f in self.state.findings if f.id==self.state.active_finding_id),None)
            if phase=="build":
                previous=model or next((m for m in reversed(self.state.models) if m.unit_id==unit.previous_id),None)
                context=self.context(unit)
                if previous:
                    context.update(previous_bundle=json.loads(Path(previous.bundle_path).read_text()),scope_delta={"before":previous.scope.model_dump(),"after":unit.scope.model_dump(),"added_bindings":list(set(unit.binding_ids)-set(previous.binding_ids)),"boundary_changes":unit.boundary_changes})
                reply,_=self.ask("F3" if unit.previous_id else "build",BuildReply,context)
                if reply.bundle is None:
                    self.targeted_read(unit,reply.gap,requests=reply.requests); self.advance("build"); continue
                model=save_bundle(self.root,self.state,unit,reply.bundle,self.implementation,previous)
                self.state.active_model_id=model.id
                if self.state.first_model_seconds is None: self.budget.sync(); self.state.first_model_seconds=self.state.elapsed_seconds
                self.advance("experiment" if self.config.allow_experiments else "search")
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
                if failed:
                    self.state.active_finding_id=failed.id; failed.stage=Investigation.REACHABILITY_PENDING
                    self.advance("replay_plan")
                else:
                    self.advance("expand")
            elif phase=="expand":
                dependencies=[e for e in self.state.relations if e.source in unit.obligation_ids and e.kind=="boundary" and e.target not in unit.obligation_ids+unit.binding_ids]
                if not dependencies: self.finish_unit(unit); return
                edge=dependencies[0]
                if not any(b.id==edge.target or b.claim_id==edge.target for b in self.state.bindings):
                    self.targeted_read(unit,edge.rationale,[edge.id])
                    edge=next(e for e in self.state.relations if e.id==edge.id)
                self.budget.take("revisions")
                check=next(c for c in reversed(self.state.checks) if c.action=="model_check" and c.model_id==model.id)
                f=Feedback(kind="F3",rationale="Explain the unresolved boundary through its actual producer",evidence_ids=[check.id],target_ids=[unit.id],relation_ids=[edge.id],new_basis="",graph=None,bundle=None)
                apply_feedback(self.state,unit,bundle,f)
                self.state.active_unit_id=None; self.state.active_model_id=None; self.advance("select"); return
            elif phase=="replay_plan":
                if not self.config.allow_experiments: raise Blocked("Candidate replay disabled by experiment permission")
                search=next(c for c in self.state.checks if c.id==finding.check_id)
                plan,_=self.ask("replay",ReplayPlan,{**self.context(unit),"bundle":bundle.model_dump(mode="json"),"finding":finding.model_dump(mode="json"),"candidate_trace":self.error_context(search)})
                if plan.checker_id!=finding.checker_id: raise Blocked("Replay plan targets another checker")
                revised=bundle.model_copy(deep=True); revised.harness=plan.harness
                new=save_bundle(self.root,self.state,unit,revised,self.implementation,model,"Initial candidate experiment plan; not F4")
                self.state.active_model_id=new.id; self.advance("replay")
            elif phase=="assess":
                record=assess_execution(self.state,model,bundle,experiment,calibration,finding,extract_events(experiment))
                path=self.root/"findings"/finding.id/(experiment.id+".json"); write_json(path,record); finding.confirmation_path=str(path)
                if record["confirmed"]: self.finish_unit(unit); return
                if record["prerequisites"]["status"]=="not_reached": self.advance("feedback_F4")
                else: self.advance("diagnose")
            elif phase in {"feedback_F1","feedback_F4","diagnose"}:
                kind=phase.removeprefix("feedback_")
                context={**self.context(unit),"bundle":bundle.model_dump(mode="json"),"model_id":model.id,
                    "calibration":calibration.model_dump(mode="json") if calibration else None,
                    "experiment":self.error_context(experiment) if experiment else None,"events":extract_events(experiment) if experiment else [],
                    "finding":finding.model_dump(mode="json") if finding else None,
                    "last_assessment":self.state.monitor_results[-1] if self.state.monitor_results else None}
                f,_=self.ask(kind,Feedback,context)
                if f.requests:
                    self.targeted_read(unit,f.rationale,requests=f.requests); self.advance(phase); continue
                if f.kind=="unresolved":
                    self.state.gaps.append(f.rationale); self.finish_unit(unit,"blocked"); return
                if kind in {"F1","F4"} and f.kind!=kind: raise Blocked("Feedback attempts to change a different semantic object")
                self.budget.take("revisions")
                old_version=self.state.graph_version
                updated=apply_feedback(self.state,unit,bundle,f)
                if f.kind=="F2":
                    if old_version==self.state.graph_version: self.finish_unit(unit,"blocked"); return
                    self.state.active_model_id=None; self.state.active_finding_id=None; self.advance("build")
                elif f.kind=="F3":
                    self.state.active_unit_id=None; self.state.active_model_id=None; self.advance("select"); return
                elif updated:
                    new=save_bundle(self.root,self.state,unit,updated,self.implementation,model,f.kind+" revision")
                    self.state.active_model_id=new.id
                    self.advance("replay" if f.kind=="F4" or finding else "experiment")
                else: self.finish_unit(unit,"blocked"); return
            elif phase=="technical_repair":
                self.budget.take("technical_repairs")
                failure=next(c for c in self.state.checks if c.id==self.state.pending_feedback["check_id"])
                reply,_=self.ask("technical",BuildReply,{**self.context(unit),"bundle":bundle.model_dump(mode="json"),"failure":self.error_context(failure)})
                if reply.bundle is None:
                    self.targeted_read(unit,reply.gap,requests=reply.requests); self.advance("technical_repair"); continue
                repaired=reply.bundle
                if repaired.checker_specs()!=bundle.checker_specs() or repaired.scope!=bundle.scope:
                    raise Blocked("Technical repair changed property scope or attribution")
                if self.state.pending_feedback["technical_phase"]!="search" and (repaired.behavior!=bundle.behavior or repaired.properties!=bundle.properties):
                    raise Blocked("Compilation repair cannot change model semantics")
                new=save_bundle(self.root,self.state,unit,repaired,self.implementation,model,"Bounded technical repair; no semantic attribution")
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
                if self.state.active_unit_id:
                    active=next(u for u in self.state.units if u.id==self.state.active_unit_id)
                    self.process_unit(active)
                    continue
                if not any(u.status == "pending" for u in self.state.units):
                    self.state.stop_reason = "No pending executable audit units; unresolved gaps remain"
                    break
                if self.state.usage.get("audit_units", 0) >= self.config.budget.audit_units:
                    raise BudgetExhausted("Audit-unit budget exhausted")
                unit = select_unit(self.state)
                if unit is None:
                    self.state.stop_reason = "No pending executable audit units; unresolved gaps remain"
                    break
                self.budget.take("audit_units"); self.state.active_unit_id=unit.id; self.checkpoint("relation_driven_selection")
                self.process_unit(unit)
        except (BudgetExhausted, Blocked, ValueError, OSError) as exc:
            self.state.stop_reason = str(exc)
            self.state.gaps.append(str(exc))
        finally:
            self.checkpoint("stopped")
        return self.state
