"""One native investigation: accept file products, execute them, retain evidence."""
import json
import os
import stat
from pathlib import Path
from pydantic import ValidationError

from consensus_assurance.adapters.storage.files import digest, write_json
from consensus_assurance.adapters.runners.experiment import extract_events, install_harness, run_experiment
from consensus_assurance.core.submissions import (NativeSubmission, SourceRange, CandidateSubmission,
    CheckSubmission, ModelSubmission, ResearchSubmission, SemanticSubmission, ReviewSubmission, ExploreSubmission)
from consensus_assurance.core.proposals import (DirectCheckPlan, ModelDraft, Feedback,
    Harness, GraphPatch, UnitDraft)
from consensus_assurance.core.types import (Material, QuestionCandidate, Revision, ConsensusAuditSpec,
    CheckRun, ExecutionStatus)
from .budget import BudgetExhausted
from .direct_checks import (assess, execute as execute_direct_check, load_plan, save_plan,
    validate_plan, validate_question, refresh_assessments)
from .transactions import commit_graph
from .errors import Blocked


def draft_file(root: Path, name: str) -> Path:
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Submission paths must be relative to the native draft directory")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Submission paths cannot traverse symlinks")
    if root.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Submission file is missing or escapes the native draft directory")
    return path


def draft_bytes(root, name):
    draft_file(root, name)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = Path(name).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Submission input must be a regular file")
            return stream.read()
    finally:
        os.close(descriptor)


class Inputs:
    """Read each submitted file once; resume reads the saved bytes, never mutable drafts."""
    def __init__(self, draft, archive):
        self.draft, self.archive = draft, archive

    def read(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Invalid submitted input path")
        saved = self.archive / "inputs" / relative
        if not saved.exists():
            data = draft_bytes(self.draft, name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(data)
        return draft_file(self.archive / "inputs", name).read_text()

    def json(self, name):
        return json.loads(self.read(name))


def harness_files(inputs, submission, raw):
    if raw.get("source") or raw.get("files"):
        raise ValueError("Harness content must come from separate submitted files")
    raw["source"] = inputs.read(submission.harness_path)
    raw["files"] = {name: inputs.read(path) for name, path in submission.files.items()}


def add_support(implementation, harness):
    support = getattr(implementation, 'support_files', lambda:{})()
    if set(support) & set(harness.files):raise ValueError('Submitted files cannot replace selected backend support')
    harness.files.update(support)


def plan_from_files(inputs, submission):
    raw = inputs.json(submission.plan_path)
    harness_files(inputs, submission, raw["harness"])
    return DirectCheckPlan.model_validate(raw)


def model_from_files(inputs, submission):
    raw = inputs.json(submission.model_path)
    if raw.get("behavior") or raw.get("properties"):
        raise ValueError("Supply Behavior and Properties through separate source files")
    raw["behavior"] = inputs.read(submission.behavior_path)
    raw["properties"] = inputs.read(submission.properties_path)
    return ModelDraft.model_validate(raw)


def require_unit(state, id):
    unit = next((u for u in state.units if u.status != 'revised' and (u.id == id or u.candidate_id == id)), None)
    if unit is None:
        raise ValueError("Select an accepted audit unit")
    return unit


def model_owner(state, unit_id, research_ref, scope):
    if unit_id:return require_unit(state,unit_id)
    from .audit_spec import load, audit_object_index
    from consensus_assurance.core.types import AuditUnit
    candidate = next((c for c in state.question_candidates if c.id==research_ref),None)
    surface = audit_object_index(load(state)).get(research_ref,{})
    if candidate is None and not surface.get('entry_point'):
        raise ValueError('Model exploration requires an accepted Candidate or mapped/deferred Surface')
    # A transient scope view reuses model validation; it creates no Unit or claim.
    return AuditUnit(id=research_ref,obligation_ids=[],binding_ids=[],relation_ids=[],scope=scope,
        rationale='Exploratory history only',audit_question=candidate.question if candidate else None)


def candidate(engine, submission, operation_id, spec=None):
    state = engine.state
    current = next((c for c in state.question_candidates if c.id == submission.candidate_id), None)
    parent = next((c for c in state.question_candidates if c.id == submission.parent_candidate_id), None)
    if submission.candidate_id and current is None or submission.parent_candidate_id and parent is None:
        raise ValueError("Candidate ID must name a saved investigation")
    selected = {c.id for c in (current, parent) if c}
    released=[]
    for other in state.question_candidates:
        if other.status in {"active","escalated"} and other.id not in selected:
            other.status, other.stop_reason = 'paused', submission.rationale
            other.resume_conditions = ['Reassess the retained question against its current execution results and sourced unknowns']
            released.append(other.id)
    if released:
        state.selections[-1]['released_candidate_ids']=released
        if any(u.id==state.active_unit_id and u.candidate_id in released for u in state.units):
            state.active_unit_id=state.active_direct_check_id=state.active_model_id=None
    q = submission.question
    validate_question(q)
    known = {m.id for m in state.materials}
    if not q.source_ids or not set(q.source_ids) <= known or not any(
            m.id in q.source_ids and m.file in state.snapshot.files for m in state.materials):
        raise ValueError("Question needs actual authorized source citations")
    from .audit_spec import require_basis, require_overview, QUESTION_BASIS
    if current is None:require_overview(state,spec)
    require_basis(state,q,spec,engine.config.activity_focus,current.id if current else None)
    if parent and q == parent.question:
        raise ValueError("A fork needs a distinct sourced question")
    if submission.action == "explained" and (not q.counterevidence or q.disposition != "explained_by_existing_mechanism"):
        raise ValueError("Explained disposition needs scoped sourced counterevidence")
    if current:
        from .research import source_refs
        answered = submission.feedback and source_refs(state,submission.feedback.ref_ids)
        update = submission.feedback.question_updates.get(current.id) if submission.feedback else None
        changed_answer = any(getattr(q,k)!=getattr(current.question,k) for k in ('unknowns','counterevidence','disposition')) or bool(update and update.unknowns!=current.question.unknowns)
        progress=bool(answered and changed_answer or any(getattr(q,k)!=getattr(current.question,k)
            for k in ('fact_ids','behavior_ids','obligation_relation_kind','contexts','event_paths')))
        if submission.action == "continue" and current.status == "active" and not progress:
            raise ValueError("Candidate continuation made no observable research change; wording alone is not progress")
        if current.obligation_id and any(getattr(q,k)!=getattr(current.question,k) for k in QUESTION_BASIS):
            raise ValueError("An accepted obligation's question needs an attributed semantic revision")
        if ((not set(current.question.counterevidence) <= set(q.counterevidence) or
                not set(current.question.unknowns) <= set(q.unknowns)) and
                not answered):
            raise ValueError("Use feedback.answered with retained source ownership to explain changed counterevidence or unknowns")
        if current.question!=q:current.history.append(current.question.model_copy(deep=True))
        current.question = q
        current.resume_conditions = []
        if progress:current.stagnation=0
    else:
        if parent and parent.status == "active":
            parent.status = "paused"
            parent.stop_reason = submission.rationale
            parent.resume_conditions = ['Revisit the parent discriminator after child results; see the saved result_implications']
        current = QuestionCandidate(question=q, parent_candidate_id=parent.id if parent else None,
            fork_reason=json.dumps(submission.result_implications) if parent else "")
        state.question_candidates.append(current)
    current.check_ids.append(operation_id)
    current.status = {"continue":"active", "pause":"paused", "explained":"explained", "obligation":"escalated"}[submission.action]
    current.stop_reason = submission.rationale
    current.resume_conditions = submission.resume_conditions
    if submission.action in {'pause','explained'} and any(u.id==state.active_unit_id and u.candidate_id==current.id for u in state.units):
        state.active_unit_id=state.active_direct_check_id=state.active_model_id=None
    if submission.action == "obligation":
        from .research import capacity
        if not capacity(state)['new_obligation']:
            raise ValueError('No remaining authorized capacity to check a new obligation; continue source research or compare another available direction')
        if q.disposition != "ready_for_check":
            raise ValueError("Obligation requires a ready_for_check question")
        from .graph import apply_patch
        claim = submission.obligation
        unit = UnitDraft(id="unit-" + claim.id, candidate_id=current.id, obligation_ids=[claim.id],
            binding_ids=[b.id for b in submission.bindings], relation_ids=[], scope=claim.scope,
            rationale=submission.rationale, audit_question=q)
        if claim.id in {c.id for c in state.claims}:
            raise ValueError("Existing obligation requires semantic_revision")
        apply_patch(state, GraphPatch(claims=[claim], bindings=submission.bindings, units=[unit], rationale=submission.rationale), audit_spec=spec)
        engine.budget.take("audit_units")
        current.obligation_id = claim.id
        state.active_unit_id = unit.id
    return current


def validate_check_revision(state, prior, plan, submission):
    old = load_plan(prior.plan_path)
    if submission.encoding_revision:
        from .encoding import validate_direct_encoding
        validate_direct_encoding(state, prior, old, plan, submission.encoding_revision)
    else:
        left, right = old.model_dump(), plan.model_dump()
        for value in (left, right):
            value.pop('description')
            for field in ("source", "files", "description", "semantic_changes"):
                value["harness"].pop(field)
            value['harness']['legality'].pop('derivation')
            value['harness']['prerequisites']=sorted(value['harness']['prerequisites'],key=lambda r:r['alias'])
            for prop in value['observable_properties']:prop.pop('description')
        if left != right:
            raise ValueError("Ordinary repair preserves the claim, oracle, prerequisites and legality; use attributed encoding/F2/F3")


def validate_model_revision(state, prior, model, submission):
    from .artifacts import load_model
    old = load_model(prior)
    if submission.encoding_revision:
        from .encoding import validate_encoding
        validate_encoding(state, prior, old, model, submission.encoding_revision)
    else:
        from .modeling import validate_technical_repair
        validate_technical_repair(old, model)


def accept(engine, submission, inputs, operation_id):
    """Runs on a transaction copy; rejected products never mutate accepted research."""
    from .research import global_stop
    if global_stop(submission.model_dump()) and submission.reason in {'resource_limit','user_stop','tool_gap'}:
        from .research import stop_record
        stop_record(engine, submission.model_dump(mode='json'), operation_id)
        return
    if isinstance(submission,CheckSubmission) and submission.candidate:
        outer,inner=submission.feedback,submission.candidate.feedback
        if outer and inner and outer!=inner:raise ValueError('Combined submission has conflicting research feedback')
        if submission.repair_of and submission.candidate.repair_of and submission.repair_of!=submission.candidate.repair_of:
            raise ValueError('Combined submission has conflicting repair_of operations')
        submission=submission.model_copy(update={'feedback':outer or inner,'repair_of':submission.repair_of or submission.candidate.repair_of,
            'candidate':submission.candidate.model_copy(update={'feedback':outer or inner})})
    state = engine.state
    research_before = state.model_copy(deep=True)
    state.materials.extend(source_materials(engine, submission.sources))
    mapped=submission.candidate if isinstance(submission,CheckSubmission) and submission.candidate else submission
    if mapped is not submission:
        state.materials.extend(source_materials(engine,mapped.sources))
    from . import audit_spec
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    spec=audit_spec.load(state)
    proposed=None
    issues=[]
    def collect_validation(check):
        try:check()
        except ValueError as exc:
            issues.extend(getattr(exc,'diagnostics',None) or [Diagnostic(code='submission',category='semantic',message=str(exc))])
    changes=getattr(mapped,'map_changes',{})
    if getattr(mapped,'map_path',None):
        proposed=ConsensusAuditSpec.model_validate(inputs.json(mapped.map_path))
        collect_validation(lambda:audit_spec.validate(state,proposed,changes))
        if audit_spec.map_delta(spec,proposed):
            spec=proposed.model_copy(deep=True)
            spec.version=state.audit_spec_version+1
    elif changes:raise ValueError('Map change declarations require a complete map file')
    def question_version(q, candidate_id=None):
        prior=next((c.question for c in research_before.question_candidates if c.id==candidate_id),None)
        if prior:
            if q.audit_spec_version is not None:return
            if all(getattr(q,k)==getattr(prior,k) for k in audit_spec.QUESTION_BASIS if k!='audit_spec_version'):
                q.audit_spec_version=prior.audit_spec_version
                return
        if proposed is not None:
            if q.audit_spec_version not in {None,proposed.version}:
                raise ValueError(f'Question base version must match submitted map base {proposed.version}; got {q.audit_spec_version}')
            q.audit_spec_version=spec.version
        elif q.audit_spec_version is None and spec:
            q.audit_spec_version=spec.version
    def patch_versions(patch, declarations=None):
        from consensus_assurance.core.proposals import JudgmentChange
        for draft in patch.units:
            if not draft.audit_question:continue
            original=draft.audit_question.model_dump(mode='json')
            question_version(draft.audit_question)
            if declarations is None or original==draft.audit_question.model_dump(mode='json'):continue
            declared=next((d for d in declarations if d.target_id==draft.id and d.field=='audit_question'),None)
            if declared and json.loads(declared.new_value_json)!=original:raise ValueError('Declared question differs from its submitted patch')
            if declared is None:
                old=next((u for u in state.units if u.id==draft.id),None)
                if old is None:continue
                basis=old.audit_question.model_dump(mode='json')
                if dict(original,audit_spec_version=basis['audit_spec_version'])!=basis:
                    raise ValueError('Question semantic changes require their own declaration; only version metadata is controller-derived')
                declared=JudgmentChange(target_id=draft.id,field='audit_question',old_value_json=old.audit_question.model_dump_json(),new_value_json='null')
                declarations.append(declared)
            declared.new_value_json=draft.audit_question.model_dump_json()
    if isinstance(mapped,CandidateSubmission):
        collect_validation(lambda:question_version(mapped.question,mapped.candidate_id))
        collect_validation(lambda:validate_question(mapped.question))
        if spec and mapped.question.audit_spec_version==spec.version:
            collect_validation(lambda:audit_spec.validate_question(spec,mapped.question,engine.config.activity_focus))
        missing=set(mapped.question.source_ids)-{m.id for m in state.materials}
        if missing:issues.append(Diagnostic(code='question_sources',category='material',message='Question has unacquired sources: '+', '.join(sorted(missing))))
        if mapped.obligation:
            from .graph_diagnostics import validate_grounding
            collect_validation(lambda:validate_grounding(mapped.obligation.grounding,
                {m.id:m for m in state.materials},{b.id for b in state.bindings}|{b.id for b in mapped.bindings}))
    if issues:raise DiagnosticError(issues)
    from .research import record_decision
    decision=record_decision(engine,submission,operation_id,map_changed=bool(proposed and audit_spec.map_delta(audit_spec.load(state),proposed)))
    decision['map_changes']={k:v.model_dump(mode='json') for k,v in changes.items()}
    decision['accepted_versions']={'audit_spec':spec.version if spec else 0}
    if decision['map_updated']:
        delta,effects=audit_spec.understanding_changes(state,proposed,changes)
        decision.update(map_delta=delta,map_effects=effects)
        audit_spec.record_challenges(state,research_before,effects,operation_id)
    def validate_objects():
        for id,q in getattr(mapped,'reconnect_questions',{}).items():
            question_version(q)
            prior=next((c for c in research_before.question_candidates if c.id==id),None)
            c=next((c for c in state.question_candidates if c.id==id),None)
            if not proposed or not audit_spec.map_delta(audit_spec.load(research_before),proposed) or not prior or not c:
                raise ValueError('Question reconnection needs a changed map and a saved Candidate')
            validate_question(q)
            audit_spec.require_basis(state,q,spec,engine.config.activity_focus,c.id)
            if not q.source_ids or not set(q.source_ids)<={m.id for m in state.materials}:raise ValueError('Reconnected question needs actual acquired sources')
            from .research import source_refs
            if (not set(prior.question.counterevidence)<=set(q.counterevidence) or not set(prior.question.unknowns)<=set(q.unknowns)) and not (submission.feedback and source_refs(state,submission.feedback.ref_ids)):
                raise ValueError('Reconnection answers require sourced feedback, preserving earlier questions in history')
            if c.question!=q:
                c.history.append(c.question.model_copy(deep=True));c.question=q
        audit_spec.validate_units(state,spec,engine.config.activity_focus)
        if len(state.claims)+len(state.bindings)+len(state.relations)+len(state.units)>engine.config.budget.graph_objects:
            raise ValueError('Accepted graph object budget exceeded')
    current = {"phase":"accepted", "operation_id":operation_id, "action":submission.action}
    if isinstance(submission, CandidateSubmission):
        candidate(engine, submission, operation_id, spec)
    elif isinstance(submission, CheckSubmission):
        if submission.candidate:audit_spec.require_overview(state,spec)
        require_capacity(engine,'experiments')
        if submission.previous_check_id:require_capacity(engine,'revisions')
        if submission.candidate:
            candidate(engine, submission.candidate, operation_id, spec)
        unit = require_unit(state, submission.unit_id or 'unit-' + submission.candidate.obligation.id)
        if not engine.config.allow_experiments:
            raise ValueError("Formal execution is not authorized")
        plan = plan_from_files(inputs, submission)
        add_support(engine.implementation, plan.harness)
        validate_plan(state, unit, plan, engine.implementation)
        install_harness(engine.root / "source", engine.implementation.harness_filename, plan.harness,
            state.snapshot.files, write=False)
        prior = next((a for a in state.direct_checks if a.id == submission.previous_check_id), None)
        if submission.previous_check_id:
            if prior is None or prior.unit_id != unit.id:
                raise ValueError("Previous check must belong to the same selected unit")
            validate_check_revision(state, prior, plan, submission)
            engine.budget.take("revisions")
        validate_objects()
        artifact = save_plan(engine, unit, plan, operation_id, prior)
        if prior:
            state.revisions.append(Revision(kind="encoding" if submission.encoding_revision else "F4",
                rationale=submission.rationale, target_ids=[prior.id],
                evidence_ids=[c.id for c in state.checks if c.direct_check_id == prior.id],
                before={"direct_check_id":prior.id}, after={"direct_check_id":artifact.id,
                "encoding_revision":submission.encoding_revision.model_dump(mode="json") if submission.encoding_revision else None}, return_step="experiment"))
        current["direct_check_id"] = artifact.id
        state.active_unit_id, state.active_direct_check_id = unit.id, artifact.id
    elif isinstance(submission, ModelSubmission):
        require_capacity(engine,'model_checks',2)
        if submission.previous_model_id:require_capacity(engine,'revisions')
        from .artifacts import validate_bundle, save_bundle, load_model
        if engine.verifier is None:raise ValueError('Model tool is not configured; select verifier_backend=tlc for a new run')
        draft = model_from_files(inputs, submission)
        unit = model_owner(state,submission.unit_id,submission.research_ref,draft.scope)
        model = validate_bundle(state, unit, draft, engine.implementation)
        previous = next((m for m in state.models if m.id == submission.previous_model_id), None)
        if submission.previous_model_id:
            if previous is None or (previous.unit_id or previous.research_ref) != unit.id:
                raise ValueError("Previous model must belong to the selected unit")
            validate_model_revision(state, previous, model, submission)
            engine.budget.take("revisions")
        validate_objects()
        artifact = save_bundle(engine.root, state, unit, model, engine.implementation, previous,
            submission.rationale, transaction_key=operation_id, validated=True)
        if previous:
            old = load_model(previous)
            kind = "encoding" if submission.encoding_revision else "F1"
            if model.behavior != old.behavior or model.properties != old.properties:
                state.affect([previous.id], submission.rationale)
            state.revisions.append(Revision(kind=kind,
                rationale=submission.rationale, target_ids=[previous.id], evidence_ids=[c.id for c in state.checks if c.model_id == previous.id],
                before={"model_id":previous.id}, after={"model_id":artifact.id}, return_step="experiment"))
        state.active_unit_id, state.active_model_id = artifact.unit_id or None, artifact.id
        current["model_id"] = artifact.id
    elif isinstance(submission, ResearchSubmission):
        if submission.graph_path:
            from .graph import apply_patch
            patch = GraphPatch.model_validate(inputs.json(submission.graph_path))
            from .research import capacity
            if patch.units and not capacity(state)['new_obligation']:
                raise ValueError('No remaining capacity for a new checkable Unit; retain sourced map research without a placeholder obligation')
            if patch.units:audit_spec.require_overview(state,spec)
            patch_versions(patch)
            apply_patch(state, patch, audit_spec=spec)
            for unit in patch.units:
                engine.budget.take("audit_units")
        if submission.scope_path:
            from .scope_updates import ScopeUpdate, apply_scope_update
            update = ScopeUpdate.model_validate(inputs.json(submission.scope_path))
            patch_versions(update.patch, update.changes)
            engine.budget.take("revisions")
            new = apply_scope_update(state, update, audit_spec=spec)
            state.scope_updates[update.id] = {"status":"accepted", "proposal":update.model_dump(mode="json"), "new_unit_id":new.id}
            reconnect_candidate(state,new)
    elif isinstance(submission, SemanticSubmission):
        from .feedback import apply_feedback
        unit = require_unit(state, submission.unit_id)
        feedback = Feedback.model_validate(inputs.json(submission.feedback_path))
        if feedback.kind not in {"F2", "F3"} or feedback.requests:
            raise ValueError("Semantic submission needs complete attributed F2/F3; use native reads first")
        if feedback.patch:patch_versions(feedback.patch, feedback.changes)
        engine.budget.take("revisions")
        apply_feedback(state, unit, None, feedback, audit_spec=spec)
        revised_ids={u.id for u in feedback.patch.units} if feedback.patch else {unit.id}
        for new in state.units:
            if new.status!='revised' and (new.id in revised_ids or new.previous_id==unit.id):reconnect_candidate(state,new)
    elif isinstance(submission, ReviewSubmission):
        from .reviews import accept_review
        require_capacity(engine,'semantic_reviews')
        engine.budget.take("semantic_reviews")
        accept_review(state, submission, operation_id)
    elif isinstance(submission, ExploreSubmission):
        require_capacity(engine,'experiments')
        if not engine.config.allow_experiments or engine.implementation is None:
            raise ValueError("Exploratory execution is not authorized or configured")
        harness = Harness(kind=engine.implementation.harness_kind, source=inputs.read(submission.harness_path),
            files={name:inputs.read(path) for name, path in submission.files.items()},
            description=submission.question, semantic_changes=[])
        add_support(engine.implementation, harness)
        install_harness(engine.root / "source", engine.implementation.harness_filename, harness,
            state.snapshot.files, write=False)
        current["harness"] = harness.model_dump(mode="json")
    else:
        current.update(scope=submission.scope,reason=submission.reason)
        if global_stop(current):
            state.stop_reason = f"Scoped stop ({submission.scope}/{submission.reason}): " + submission.rationale
    if submission.feedback:
        for id,update in submission.feedback.question_updates.items():
            c=next(c for c in state.question_candidates if c.id==id)
            if update.resume_conditions and c.status!='paused':raise ValueError('Feedback resume_conditions require a paused Candidate')
            if c.question.unknowns!=update.unknowns:c.history.append(c.question.model_copy(deep=True))
            c.question.unknowns=list(update.unknowns)
            c.resume_conditions=list(update.resume_conditions)
            for unit in state.units:
                if unit.candidate_id==id and unit.status!='revised':unit.audit_question.unknowns=list(update.unknowns)
    # Forced/resource exits are always possible, even with incomplete historical understanding.
    if submission.action not in {'stop','explore','review'}:validate_objects()
    sync_progress(engine)
    if proposed is not None:audit_spec.accept(engine,proposed)
    decision=state.selections[-1]
    decision['candidate_ids']=list(dict.fromkeys(decision.get('candidate_ids',[])+[c.id for c in state.question_candidates if operation_id in c.check_ids]))
    decision['accepted_versions']={'audit_spec':state.audit_spec_version,
        'units':{u.id:u.version for u in state.units if u not in research_before.units},
        'artifacts':{a.id:a.version for a in state.models+state.direct_checks if a not in research_before.models+research_before.direct_checks}}
    state.native_current = current


def require_capacity(engine, resource, amount=1):
    available=getattr(engine.config.budget,resource)-engine.state.usage.get(resource,0)
    if available<amount:
        raise ValueError(f'Local capability unavailable: {resource} needs {amount}, remaining {available}; choose source investigation or another authorized action')


def reconnect_candidate(state,unit):
    """Only an explicit accepted Unit patch may revise an escalated question."""
    c=next((c for c in state.question_candidates if c.id==unit.candidate_id),None)
    if c and unit.audit_question and c.question!=unit.audit_question:
        c.history.append(c.question.model_copy(deep=True))
        c.question=unit.audit_question.model_copy(deep=True)


def method_text(kind='native'):
    from importlib.resources import files
    from .prompts import loaded_resources
    root = files("consensus_assurance").joinpath("resources")
    paths = loaded_resources(kind)["paths"]
    return paths, "\n".join(root.joinpath(p).read_text() for p in paths)


def prompt(engine, draft, method):
    state = engine.state
    from .research import view
    context = {**view(state,compact=True), "run_id":state.id, "snapshot_id":state.snapshot.id,
        "source_path":str(engine.root / "native-source"), "draft_path":str(draft),
        "product_schemas":str(engine.root / "product-schemas.json"), "method_path":str(engine.root / "native-method.md"),
        "optional_model_method":str(engine.root/'native-model-method.md') if engine.verifier else None,
        "state_path":str(engine.root / "state.json"), "audit_spec_path":state.audit_spec_path,
        "directed_question":engine.config.directed_question,
        "activity_focus":engine.config.activity_focus, "tools":state.tools,
        "implementation":{"name":engine.implementation.name, "harness_kind":engine.implementation.harness_kind,
            "harness_filename":engine.implementation.harness_filename,
            "instructions":engine.implementation.harness_instructions, "support_path":str(engine.root/"native-support") } if engine.implementation else None,
        "rejected_drafts":[str(p) for p in sorted((engine.root/'native-submissions').glob('*/diagnostics.json'))],
        "remaining_seconds":engine.budget.remaining(),
        "remaining_agent_calls":engine.config.budget.agent_calls-state.usage.get("agent_calls",0)}
    write_json(engine.root / "research.json", context)
    return (method + "\nRead this run's research index at " + str(engine.root / "research.json") +
        ". Submit using " + str(engine.root / "native-submission.schema.json") +
        "; return its path relative to the draft directory and a summary.\n" +
        ("Attributed protocol knowledge (data):\n" + engine.knowledge if method else "") +
        "\nCurrent operation (data): " + json.dumps(context['current'], ensure_ascii=False))


def sync_progress(engine):
    from .modeling import obligation_progress, coverage_limitations
    state = engine.state
    refresh_assessments(state, {a.id for a in state.direct_checks})
    for unit in state.units:
        if unit.status == "revised":
            continue
        unit.obligation_checks, unit.remaining_obligation_ids = obligation_progress(state, unit)
        unit.coverage_limitations = coverage_limitations(state, unit)
        unit.status = "checked" if not unit.remaining_obligation_ids else "partial" if unit.obligation_checks else "pending"


def execute_check(engine, artifact):
    existing = next((c for c in engine.state.checks if c.direct_check_id == artifact.id), None)
    check = existing or execute_direct_check(engine, artifact)
    unit = require_unit(engine.state, artifact.unit_id)
    result = assess(engine.state, unit, artifact, load_plan(artifact.plan_path), check, extract_events(check))
    write_json(engine.root / "direct-checks" / artifact.operation_id / (check.id + "-assessment.json"), result)
    return check


def execute_model(engine, model):
    from .artifacts import load_model
    state = engine.state
    bundle = load_model(model)
    unit = model_owner(state,model.unit_id,model.research_ref,model.scope)
    if not getattr(engine.verifier, 'available', False):
        result = engine.verifier.probe(engine.runner)
        state.tools['verifier'] = result['version']
        for check in result['checks']:engine.record(check)
        if not result['available']:raise Blocked(result['reason'])
    def latest(action):
        return next((c for c in reversed(state.checks) if c.model_id == model.id and c.action == action), None)
    if hasattr(engine.verifier, "syntax"):
        syntax = latest("model_syntax")
        if syntax is None:
            syntax = CheckRun.model_validate(engine.action("model_syntax", "model_checks",
                lambda:engine.verifier.syntax(engine.runner, model, engine.budget.timeout()), {"model_id":model.id}))
            syntax.model_id = model.id
            engine.record(syntax)
        if syntax.status != ExecutionStatus.COMPLETED or syntax.exit_code != 0:
            state.gaps.append("Model syntax incomplete; inspect " + str(syntax.stderr))
            return
    check = latest("model_check") or engine.search(unit, model, bundle, None)
    if check.status == ExecutionStatus.COMPLETED and bundle.reachability:
        engine.check_triggers(model, bundle)


def execute_accepted(engine):
    current, state = engine.state.native_current, engine.state
    try:
        if current.get("direct_check_id"):
            execute_check(engine, next(a for a in state.direct_checks if a.id == current["direct_check_id"]))
        if current.get("model_id"):
            execute_model(engine, next(m for m in state.models if m.id == current["model_id"]))
        if current.get("harness"):
            def run():
                workspace = engine.workspace()
                harness = Harness.model_validate(current["harness"])
                install_harness(workspace, engine.implementation.harness_filename, harness, state.snapshot.files)
                return run_experiment(engine.runner, engine.implementation.experiment_command(), workspace,
                    state.snapshot.id, engine.budget.timeout(), engine.config.execution_isolation,
                    "exploration", adapter=engine.implementation)
            check = CheckRun.model_validate(engine.action("exploration", "experiments", run,
                {"operation_id":current["operation_id"]}))
            engine.record(check)
    except (OSError, ValueError, Blocked, BudgetExhausted) as exc:
        current["execution_gap"] = str(exc)
        state.gaps.append("Accepted operation execution failed: " + str(exc))
        if isinstance(exc,BudgetExhausted) and engine.budget.remaining()<=0:
            current['phase']='accepted'
            engine.checkpoint('native_execution_deferred_at_deadline')
            return
    current["phase"] = "executed"
    sync_progress(engine)
    engine.checkpoint("native_execution_completed")


def source_materials(engine, references):
    state = engine.state
    existing = {m.id:m for m in state.materials}
    if len({r.id for r in references}) != len(references):
        raise ValueError("Duplicate source range IDs")
    additions = []
    for reference in references:
        rel = Path(reference.file)
        if rel.is_absolute() or ".." in rel.parts or reference.file not in (state.snapshot.readable_files or []):
            raise ValueError("Source citation is outside the authorized snapshot: " + reference.file)
        path = (engine.root / "source" / rel).resolve()
        if not path.is_relative_to((engine.root / "source").resolve()) or not path.is_file() or path.is_symlink():
            raise ValueError("Source citation does not resolve to an authorized regular file")
        data = path.read_bytes()
        if digest(data) != state.snapshot.files[reference.file]:
            raise ValueError("Source snapshot version changed: " + reference.file)
        lines = data.decode("utf-8").splitlines()
        if reference.end_line < reference.start_line or reference.end_line > len(lines):
            raise ValueError("Source citation range does not exist: " + reference.id)
        material = Material(id=reference.id,file=reference.file,start_line=reference.start_line,
            end_line=reference.end_line,kind=reference.kind,
            text="\n".join(lines[reference.start_line-1:reference.end_line]),
            content_digest=state.snapshot.files[reference.file])
        if reference.id in existing:
            if existing[reference.id] != material:
                raise ValueError("Source range ID reused for a different excerpt")
        else:
            additions.append(material)
    return additions


def prepare_native_source(engine):
    """Expose only configured readable files; the complete source remains for trusted execution."""
    source=engine.root/"source"
    view=engine.root/"native-source"
    allowed=set(engine.state.snapshot.readable_files or [])
    if not allowed:
        raise ValueError("No source files are authorized for native browsing")
    for name in allowed:
        path=source/name
        if name not in engine.state.snapshot.files or not path.is_file() or digest(path.read_bytes())!=engine.state.snapshot.files[name]:
            raise ValueError("Authorized source cannot be reconstructed from the captured snapshot")
    if view.exists():
        actual={str(path.relative_to(view)) for path in view.rglob("*") if path.is_file()}
        if actual!=allowed or any(path.is_symlink() for path in view.rglob("*")):
            raise ValueError("Native source view changed since it was captured")
        if any(digest((view/name).read_bytes())!=engine.state.snapshot.files[name] for name in allowed):
            raise ValueError("Native source view content changed")
        return
    for name in allowed:
        target=view/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((source/name).read_bytes())


def receive(engine, payload):
    check = CheckRun.model_validate(payload[0])
    session, result = payload[1:]
    engine.record(check)
    state = engine.state
    if session:
        state.native_session_id = session
    if not any(t['check_id'] == check.id for t in state.native_turns):
        state.native_turns.append({'check_id':check.id, 'session_id':session,
            'tool_events':check.parameters.get('native_tool_events'), 'usage':check.parameters.get('native_usage')})
    state.native_current = {'phase':'received', 'operation_id':check.id, 'result':result,
        'status':check.status.value, 'reason':check.reason,
        'session_unavailable':check.parameters.get('native_session_unavailable', False)}
    engine.checkpoint('native_receipt_saved')


def accept_received(engine, draft):
    current, state = engine.state.native_current, engine.state
    operation_id = current['operation_id']
    result = current.get('result')
    archive = engine.root / 'native-submissions' / operation_id
    archive.mkdir(parents=True, exist_ok=True)
    if current['status'] != ExecutionStatus.COMPLETED.value or not result:
        if current.get('session_unavailable'):
            state.native_session_id = None
            state.gaps.append('Native session unavailable; continue from saved research in a new session')
            current['phase'] = 'rejected'
            engine.checkpoint('native_session_unavailable')
            return False
        state.stop_reason = 'Native Agent stopped: ' + current['reason']
        current['phase'] = 'failed'
        return False
    raw={}
    try:
        if not result.get('submission'):
            raise ValueError('Completed turn supplied no reviewable submission: ' + result.get('summary', ''))
        raw_path = archive / 'raw.json'
        if not raw_path.exists():
            raw_path.write_bytes(draft_bytes(draft, result['submission']))
        raw = json.loads(raw_path.read_bytes())
        if not isinstance(raw,dict):raise ValueError('A submission must be a JSON object')
        from .research import global_stop
        if global_stop(raw) and raw.get('reason') in {'resource_limit','user_stop','tool_gap'}:
            from .research import stop_record
            stop_record(engine, raw, operation_id)
            write_json(archive / 'accepted.json', {'action':'stop','semantic_changes_applied':False})
            engine.checkpoint('native_forced_stop')
            return True
        submission = NativeSubmission.model_validate(raw)
        inputs = Inputs(draft, archive)
        commit_graph(engine, 'native-' + operation_id, submission.model_dump(mode='json'),
            lambda proxy:accept(proxy, submission, inputs, operation_id))
        write_json(archive / 'accepted.json', submission)
        return True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = {'errors':[str(exc)], 'raw_path':str(archive / 'raw.json'),
            'submitted_path':result.get('submission'), 'summary':result.get('summary')}
        if isinstance(exc,ValidationError):
            errors['errors']=['/'.join(map(str,error['loc']))+': '+error['msg']
                for error in exc.errors(include_url=False,include_input=False)]
        if hasattr(exc, 'diagnostics'):
            errors['diagnostics'] = [d.model_dump(mode='json') for d in exc.diagnostics]
        write_json(archive / 'diagnostics.json', errors)
        from .research import reject_local
        released=reject_local(state,operation_id,errors,raw if isinstance(raw,dict) else {})
        state.native_current = {'phase':'rejected', 'operation_id':operation_id, 'rejected':errors,
            'local_handoff':released}
        engine.checkpoint('native_submission_rejected')
        return False


def execute(engine):
    from .research import global_stop
    state = engine.state
    draft = engine.root / 'native-draft'
    draft.mkdir(exist_ok=True)
    paths, methods = method_text()
    for name, content in getattr(engine.implementation, 'support_files', lambda:{})().items():
        path = engine.root/'native-support'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)
    write_schemas(engine.root, bool(engine.verifier))
    (engine.root / 'native-method.md').write_text(methods)
    state.native_method_paths = paths
    if engine.verifier:
        optional_paths, optional_method = method_text('model')
        (engine.root/'native-model-method.md').write_text(optional_method)
        state.native_method_paths = list(dict.fromkeys(paths+optional_paths))
    write_json(engine.root / 'native-submission.schema.json', NativeSubmission.model_json_schema())
    # Remaining calls govern new inference, never recovery of an already durable receipt.
    pending = state.pending_action
    if pending and pending.kind == 'native_agent' and pending.status == 'completed':
        path = engine.root / 'actions' / pending.id / 'result.json'
        if path.exists() and state.native_current.get('phase') not in {'received', 'accepted'}:
            payload = json.loads(path.read_text())
            if not any(t['check_id'] == payload[0]['id'] for t in state.native_turns):
                receive(engine, payload)
    if pending and pending.kind == 'native_agent' and pending.status == 'running' and hasattr(engine.agent, 'decode'):
        receipts = [CheckRun.model_validate_json(p.read_text()) for p in (engine.root/'logs').glob('*/check.json')]
        check = next((c for c in receipts if c.pending_action_id == pending.id and c.action == 'native_agent' and c.ended_at), None)
        if check:
            response = engine.root/'actions'/pending.id/'native-response.json'
            payload = engine.action('native_agent', 'agent_calls',
                lambda:engine.agent.decode(check, response, state.native_session_id), pending.logical_input)
            receive(engine, payload)
    stop_cause='resource_limit'
    try:
        if state.native_current.get('phase') == 'received':
            accept_received(engine, draft)
        if state.native_current.get('phase') == 'accepted':
            execute_accepted(engine)
        if global_stop(state.native_current) or state.native_current.get('phase') == 'failed':
            return state
        if not engine.config.allow_agent_materials:
            raise Blocked('Native source browsing is disabled; no model payload sent')
        if not engine.agent.mock and (not engine.config.allow_experiments or engine.config.execution_isolation != 'bwrap'):
            raise Blocked('Native tool sessions require authorized isolated target execution; use plan for snapshot-only inspection')
        prepare_native_source(engine)
        if engine.knowledge:
            pack_id = 'protocol-pack:' + engine.config.protocol
            if not any(m.id == pack_id for m in state.materials):
                state.materials.append(Material(id=pack_id, file='protocol:' + engine.config.protocol,
                    start_line=1, end_line=len(engine.knowledge.splitlines()), kind='protocol_candidate',
                    text=engine.knowledge, content_digest=digest(engine.knowledge.encode())))
        if not state.tools or not getattr(engine.agent, 'available', False):
            engine.probe_tools()
        if not getattr(engine.agent, 'available', False):
            raise Blocked('Native Agent capability probe failed; no model payload sent')
        state.stop_reason = 'Not started'
        while engine.budget.remaining() > 0:
            pending = state.pending_action
            recovering = pending and pending.kind == 'native_agent' and pending.status == 'running' and any(
                c.pending_action_id == pending.id and c.ended_at for c in
                (CheckRun.model_validate_json(p.read_text()) for p in (engine.root/'logs').glob('*/check.json')))
            if not recovering and state.usage.get('agent_calls', 0) >= engine.config.budget.agent_calls:
                raise BudgetExhausted('agent_calls budget exhausted; retained local work remains visible')
            request = prompt(engine, draft, methods if not state.native_session_id else '')
            if hasattr(engine.agent, 'prepare'):
                engine.agent.read_only_roots = engine.implementation.read_only_roots() if engine.implementation else []
                engine.agent.tool_environment = engine.implementation.environment(draft) if engine.implementation else {}
                permitted, checks = engine.agent.prepare(engine.runner, draft, state.snapshot.id)
                for check in checks:
                    engine.record(check)
                if not permitted:
                    raise Blocked('Native permission probe is inconclusive or denied; inspect probe logs; no model payload sent')
            payload = engine.action('native_agent', 'agent_calls', lambda:engine.agent.investigate(
                engine.runner, request, draft, state.snapshot.id,
                min(engine.budget.remaining(), engine.config.budget.native_turn_timeout), state.native_session_id),
                {'session_id':state.native_session_id, 'turn':len(state.native_turns)})
            receive(engine, payload)
            accepted = accept_received(engine, draft)
            if state.native_current.get('phase') == 'failed':
                break
            if accepted:
                execute_accepted(engine)
                if global_stop(state.native_current):
                    break
    except (BudgetExhausted, Blocked) as exc:
        state.stop_reason = str(exc)
        stop_cause='resource_limit' if isinstance(exc,BudgetExhausted) else 'tool_gap'
    except KeyboardInterrupt:
        state.stop_reason='User interrupted the native investigation; partial work retained'
        stop_cause='user_stop'
        raise
    finally:
        if state.stop_reason == 'Not started':
            state.stop_reason = 'Native investigation reached the authorized total time budget'
        if not global_stop(state.native_current):
            from .research import stop_record
            last = state.checks[-1] if state.checks else None
            reason = ('resource_limit' if engine.budget.remaining() <= 0 or last and last.status == ExecutionStatus.TIMEOUT
                else 'user_stop' if last and last.status == ExecutionStatus.CANCELLED
                else 'tool_gap' if state.native_current.get('phase') == 'failed' else stop_cause)
            stop_record(engine, {'reason':reason, 'rationale':state.stop_reason},
                state.native_current.get('operation_id',state.id), controller=True)
        elif not state.run_stop:
            state.run_stop=next(s for s in reversed(state.selections) if s.get('action')=='stop')
        engine.checkpoint('native_stopped')
    return state


def write_schemas(root, model_enabled=False):
    from .scope_updates import ScopeUpdate
    products = [DirectCheckPlan, ConsensusAuditSpec, GraphPatch, ScopeUpdate, Feedback]
    if model_enabled:products.append(ModelDraft)
    schemas = {kind.__name__:kind.model_json_schema() for kind in products}
    write_json(root / "product-schemas.json", schemas)
