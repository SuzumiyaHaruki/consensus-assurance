import shutil
import time
from pathlib import Path
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Discovery, Bundle, Feedback
from consensus_assurance.core.types import (Analysis, Assessment, Calibration, CheckRun, Evidence, ExecutionStatus,
    Finding, Investigation, Origin, Relation, Scope, uid)
from consensus_assurance.ports.interfaces import AgentBackend, ImplementationAdapter, VerifierBackend
from .prompts import render
from consensus_assurance.adapters.runners.process import ProcessRunner, output
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events, prerequisites
from consensus_assurance.adapters.storage.files import Store, write_json, digest
from consensus_assurance.adapters.storage.snapshot import capture
from .materials import catalogue, initial_materials, add_reads, ReadingPlan
from .graph import apply_discovery, select_unit
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
        self.state = Analysis(mode="mock" if self.agent.mock else "real", config=self.config.model_dump(mode="json"), snapshot=snapshot)
        self.state.analysis_mode = "regression" if self.agent.mock else ("directed" if self.config.directed_question else "autonomous")
        self.state.elapsed_seconds = time.monotonic() - started
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        write_json(self.root / "config.json", self.config)
        write_json(self.root / "snapshot.json", snapshot)
        self.checkpoint("created")
        return self.execute(plan_only=plan_only)

    def resume(self):
        self.state = self.store.load()
        self.budget = BudgetTracker(self.config.budget, self.state)
        self.runner.deadline = time.monotonic() + self.budget.remaining()
        current = capture(Path(self.state.snapshot.repo))
        reasons = []
        if current.files != self.state.snapshot.files:
            reasons.append("Source snapshot changed")
        if self.config.model_dump(mode="json") != self.state.config:
            reasons.append("Configuration changed")
        for model in self.state.models:
            for path, expected in model.artifact_digests.items():
                if not Path(path).is_file() or digest(Path(path).read_bytes()) != expected:
                    reasons.append("Model, checker, mapping or harness artifact changed")
                    break
        copied = capture(self.root / "source")
        if copied.files != self.state.snapshot.files:
            reasons.append("Preserved source copy changed")
        if reasons:
            self.state.invalidate("; ".join(reasons))
            self.state.stop_reason = "Inputs changed; start a new run to avoid mixing evidence"
            self.checkpoint("resume_inputs_changed")
            return self.state
        if self.agent.mock:
            self.agent.cursor = self.state.usage.get("agent_calls", 0)
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
        for unit in self.state.units:
            if unit.status in {"selected", "blocked"}:
                unit.status = "pending"
        self.checkpoint("resumed_history_reused_without_reexecution")
        return self.execute(probed=True)

    def record(self, check):
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

    def ask(self, kind, response_type, context, validator=None):
        if not self.agent.mock and not self.config.allow_agent_materials:
            raise Blocked("Agent material transmission disabled by configuration; no repository payload was sent")
        original = kind
        for attempt in range(self.config.budget.repeated_error_revisions + 1):
            self.budget.take("agent_calls")
            directory = self.root / "agent" / f"{self.state.usage['agent_calls']:03d}-{original}"
            prompt = render(kind, context, self.inquiry if original in {"discover", "F3"} else "")
            check, response = self.agent.analyze(self.runner, prompt, directory, self.state.snapshot.id, self.budget.timeout(), response_type)
            self.record(check)
            if response is not None:
                try:
                    if validator:
                        validator(response)
                    return response, check
                except ValueError as exc:
                    write_json(directory / "reference-validation.json", {"error": str(exc)})
                    context = {"task": original, "previous_response": response.model_dump(mode="json"),
                        "validation_error": str(exc), "original_context": context}
            elif check.reason == "Structured agent output is invalid":
                context = {"task": original, "validation_error": (directory / "validation-error.txt").read_text(),
                    "original_context": context}
            else:
                raise Blocked(f"Agent blocked: {check.status.value}; {check.reason}")
            kind = "retry"
        raise Blocked("Structured response repair limit reached")

    def context(self, unit=None):
        result = {"materials": [m.model_dump(mode="json") for m in self.state.materials],
            "capabilities": [c.model_dump(mode="json") for c in self.state.capabilities],
            "parameters": self.config.parameters, "remaining_seconds": self.budget.remaining(),
            "directed_question": self.config.directed_question,
            "snapshot_id": self.state.snapshot.id, "harness_kind": self.implementation.harness_kind,
            "harness_instructions": self.implementation.harness_instructions}
        if unit:
            result.update({"unit": unit.model_dump(mode="json"), "claims": [c.model_dump(mode="json") for c in self.state.claims],
                "bindings": [b.model_dump(mode="json") for b in self.state.bindings if b.id in unit.binding_ids],
                "relations": [e.model_dump(mode="json") for e in self.state.relations]})
        return result

    def discover(self):
        source = self.root / "source"
        if "materials" not in self.state.completed_steps:
            self.state.materials = initial_materials(source, self.state.snapshot, self.config.budget, self.knowledge)
            inventory = catalogue(source, self.state.snapshot)
            write_json(self.root / "catalogue.json", inventory)
            plan, _ = self.ask("read", ReadingPlan, {"catalogue": inventory, "initial_materials": [m.model_dump(mode="json") for m in self.state.materials]})
            add_reads(self.state, source, plan, self.config.budget)
            write_json(self.root / "materials.json", [m.model_dump(mode="json") for m in self.state.materials])
            self.state.completed_steps.append("materials"); self.checkpoint("material_reading_completed")
        if "discovery" not in self.state.completed_steps:
            proposal, check = self.ask("discover", Discovery, self.context(), lambda p: apply_discovery(self.state, p))
            path = self.root / f"discovery-v{self.state.graph_version}.json"
            write_json(path, proposal); self.state.discovery_path = str(path)
            self.state.completed_steps.append("discovery"); self.checkpoint("autonomous_graph_created")

    def experiment(self, model, bundle, replay=False):
        self.budget.take("experiments")
        if replay:
            self.budget.take("replays")
        workspace = self.workspace()
        destination = workspace / self.implementation.harness_filename
        if destination.exists():
            raise Blocked("Generated harness would overwrite a target file")
        destination.write_text(bundle.harness.source)
        check = run_experiment(self.runner, self.implementation.experiment_command(), workspace, self.state.snapshot.id,
            self.budget.timeout(), self.config.execution_isolation, "replay" if replay else "experiment", adapter=self.implementation)
        check.model_id = model.id; check.input_versions = model.artifact_digests
        check.tool_version = self.state.tools.get("implementation", "unknown")
        check.origin = Origin.MOCK if self.state.mode == "mock" else Origin.EXECUTED
        check.artifacts = [str(destination), model.mapping_path]
        self.record(check)
        return check

    def calibrate(self, model, bundle, experiment):
        self.budget.take("calibration_checks")
        record, checks = self.verifier.calibrate(self.runner, model, bundle, experiment, self.budget.timeout())
        for check in checks:
            self.record(check)
        self.state.calibrations.append(record)
        self.checkpoint("trace_calibration_recorded")
        return record

    def search(self, unit, model, bundle, calibration):
        self.budget.take("model_checks")
        check = self.verifier.check(self.runner, model, self.budget.timeout())
        check.origin = Origin.MOCK if self.state.mode == "mock" else Origin.EXECUTED
        self.record(check)
        if check.status == ExecutionStatus.COMPLETED and check.outcome in {"holds", "counterexample"}:
            for claim in bundle.checked_claim_ids:
                assessment = Assessment.SUPPORTED if check.outcome == "holds" else Assessment.CHALLENGED
                evidence = Evidence(check_id=check.id, model_id=model.id, snapshot_id=model.snapshot_id, claim_id=claim,
                    origin=check.origin, level="framework_test" if self.state.mode == "mock" else "model", scope=model.scope,
                    assessment=Assessment.INCONCLUSIVE if self.state.mode == "mock" else assessment,
                    calibration_id=calibration.id if calibration else None,
                    description="Finite model result only; calibration=" + (calibration.status if calibration else "not_scheduled"))
                self.state.add_evidence(evidence)
                self.state.relations.append(Relation(source=evidence.id, target=claim,
                    kind="supports" if check.outcome == "holds" else "challenges", rationale="Scoped model evidence; no implementation proof propagation"))
            if check.outcome == "counterexample":
                self.state.findings.append(Finding(claim_id=model.claim_id, model_id=model.id, check_id=check.id,
                    origin=check.origin, trace_path=check.stdout, description="Candidate model violation; legality and implementation consequences remain unconfirmed"))
        self.checkpoint("model_search_recorded")
        return check

    def process_unit(self, unit):
        context = self.context(unit)
        previous = next((m for m in reversed(self.state.models) if m.unit_id in {unit.id, unit.previous_id}), None)
        kind = "F3" if unit.previous_id else "build"
        if previous:
            context["previous_bundle"] = Bundle.model_validate_json(Path(previous.bundle_path).read_text()).model_dump(mode="json")
            context["scope_delta"] = {"old_bindings": previous.binding_ids, "new_bindings": unit.binding_ids}
        bundle, _ = self.ask(kind, Bundle, context)
        while True:
            model = save_bundle(self.root, self.state, unit, bundle, self.implementation, previous)
            if self.state.first_model_seconds is None:
                self.budget.sync(); self.state.first_model_seconds = self.state.elapsed_seconds
            self.checkpoint("generated_artifacts_saved")
            calibration = None
            experiment = None
            if self.config.allow_experiments:
                experiment = self.experiment(model, bundle)
                calibration = self.calibrate(model, bundle, experiment)
                if experiment.status == ExecutionStatus.COMPLETED:
                    self.state.add_evidence(Evidence(check_id=experiment.id, model_id=model.id, snapshot_id=model.snapshot_id,
                        claim_id=None, origin=experiment.origin, level="framework_test" if self.state.mode == "mock" else "implementation_test",
                        scope=bundle.scope, assessment=Assessment.INCONCLUSIVE,
                        calibration_id=calibration.id, description="Generated experiment execution; limited observations, not a proof or automatic reproduction"))
            else:
                self.state.gaps.append("Experiments disabled by configuration; model remains uncalibrated")
            check = self.search(unit, model, bundle, calibration)
            if check.status == ExecutionStatus.TOOL_MISSING:
                raise Blocked(check.reason)
            if check.status != ExecutionStatus.COMPLETED:
                if check.reason == "Model syntax error" and self.state.usage.get("syntax_repairs", 0) < self.config.budget.repeated_error_revisions:
                    self.budget.take("revisions"); self.state.usage["syntax_repairs"] = self.state.usage.get("syntax_repairs", 0) + 1
                    repaired, _ = self.ask("retry", Bundle, {"original_context": self.context(unit), "bundle": bundle.model_dump(mode="json"), "tool_error": output(check)})
                    if repaired.properties != bundle.properties or repaired.checked_claim_ids != bundle.checked_claim_ids:
                        raise Blocked("Executable repair changed the checked property; semantic review required")
                    previous, bundle = model, repaired
                    continue
                raise Blocked("Search did not complete: " + check.status.value)
            if calibration and calibration.status == "incompatible":
                feedback, _ = self.ask("F1", Feedback, {**self.context(unit), "bundle": bundle.model_dump(mode="json"),
                    "calibration": calibration.model_dump(mode="json"), "events": extract_events(experiment), "model_id": model.id})
                self.budget.take("revisions")
                updated = apply_feedback(self.state, unit, bundle, feedback)
                self.checkpoint("F1_feedback_processed")
                if updated is None:
                    unit.status = "blocked"; return
                previous, bundle = model, updated
                continue
            if check.outcome == "counterexample":
                finding = self.state.findings[-1]
                finding.stage = Investigation.REACHABILITY_PENDING
                feedback, _ = self.ask("diagnose", Feedback, {**self.context(unit), "bundle": bundle.model_dump(mode="json"),
                    "check_id": check.id, "model_id": model.id, "candidate_trace": output(check),
                    "experiment": experiment.model_dump(mode="json") if experiment else None,
                    "events": extract_events(experiment) if experiment else []})
                if feedback.kind == "unresolved":
                    finding.stage = Investigation.INCONCLUSIVE
                    finding.investigation_notes.append(feedback.rationale)
                    unit.status = "blocked"; self.checkpoint("candidate_unresolved"); return
                self.budget.take("revisions")
                updated = apply_feedback(self.state, unit, bundle, feedback)
                self.checkpoint(feedback.kind + "_feedback_processed")
                if feedback.kind in {"F2", "F3"}:
                    return
                if feedback.kind == "F4" and updated:
                    replay_model = save_bundle(self.root, self.state, unit, updated, self.implementation, model, "F4 experiment revision")
                    self.checkpoint("F4_experiment_artifacts_saved")
                    replay = self.experiment(replay_model, updated, replay=True)
                    self.calibrate(replay_model, updated, replay)
                    hit, reason = prerequisites(extract_events(replay), updated.harness.prerequisite_events)
                    finding.replay_check_id = replay.id; finding.stage = Investigation.INCONCLUSIVE
                    finding.investigation_notes.append(reason if updated.harness.prerequisite_events else "No executable prerequisite specification was supplied")
                    # No automatic promotion: harness assertions alone do not establish legality or target consequences.
                    if not hit:
                        self.state.gaps.append("F4: experimental preconditions were not reached")
                    self.checkpoint("F4_replay_recorded")
                    unit.status = "blocked"; return
                if updated:
                    previous, bundle = model, updated
                    continue
            # Search success does not discharge unexplained dependencies.
            dependencies = [e for e in self.state.relations if e.source in unit.obligation_ids and e.kind == "boundary"
                and e.target not in unit.obligation_ids + unit.binding_ids]
            if dependencies:
                feedback = Feedback(kind="F3", rationale="Completed local search leaves an unexplained boundary producer",
                    evidence_ids=[check.id], target_ids=[unit.id], relation_ids=[dependencies[0].id], new_basis="", graph=None, bundle=None)
                self.budget.take("revisions")
                try:
                    apply_feedback(self.state, unit, bundle, feedback)
                except ValueError as exc:
                    self.state.gaps.append("F3 expansion blocked: " + str(exc)); unit.status = "blocked"
                self.checkpoint("F3_dependency_expansion")
                return
            unit.status = "checked"
            self.checkpoint("audit_unit_checked_in_scope")
            return

    def execute(self, probed=False, plan_only=False):
        try:
            if not probed:
                self.probe_tools()
            if "capabilities" not in self.state.completed_steps:
                self.budget.take("experiments")
                workspace = self.workspace()
                check = run_experiment(self.runner, self.implementation.probe_command(), workspace, self.state.snapshot.id,
                    self.budget.timeout(), self.config.execution_isolation, "capability_probe", adapter=self.implementation)
                check.tool_version = self.state.tools.get("implementation", "unknown")
                self.record(check)
                self.state.capabilities = self.implementation.capabilities(check)
                self.state.completed_steps.append("capabilities"); self.checkpoint("capabilities_recorded")
            self.discover()
            if plan_only:
                self.state.stop_reason = "Plan generated; modeling and checks not scheduled"
                return self.state
            while True:
                if not any(u.status == "pending" for u in self.state.units):
                    self.state.stop_reason = "No pending executable audit units; unresolved gaps remain"
                    break
                if self.state.usage.get("audit_units", 0) >= self.config.budget.audit_units:
                    raise BudgetExhausted("Audit-unit budget exhausted")
                unit = select_unit(self.state)
                if unit is None:
                    self.state.stop_reason = "No pending executable audit units; unresolved gaps remain"
                    break
                self.budget.take("audit_units"); self.checkpoint("relation_driven_selection")
                self.process_unit(unit)
        except (BudgetExhausted, Blocked, ValueError, OSError) as exc:
            self.state.stop_reason = str(exc)
            self.state.gaps.append(str(exc))
        finally:
            self.checkpoint("stopped")
        return self.state
