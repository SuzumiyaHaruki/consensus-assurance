"""One audit investigation: accept file products, execute them, retain evidence."""
import json
import os
import stat
from pathlib import Path
from pydantic import ValidationError

from consensus_assurance.adapters.storage.files import digest, write_json
from consensus_assurance.adapters.runners.experiment import extract_events, install_harness
from consensus_assurance.core.submissions import (AuditSubmission, CandidateSubmission,
    CheckSubmission, ResearchSubmission, ExploreSubmission)
from consensus_assurance.core.proposals import (DirectCheckPlan, Harness, GraphPatch, UnitDraft)
from consensus_assurance.core.types import (Material, QuestionCandidate, Revision, ConsensusAuditSpec,
    CheckRun, ExecutionStatus, AuditQuestion, BindingAssociation)
from .budget import BudgetExhausted
from .direct_checks import (assess, execute as execute_direct_check, execute_harness, load_plan, save_plan,
    validate_plan, validate_question, refresh_assessments)
from .transactions import commit_graph
from .errors import Blocked


def draft_file(root: Path, name: str) -> Path:
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Submission paths must be relative to the draft directory")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Submission paths cannot traverse symlinks")
    if root.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Submission file is missing or escapes the draft directory")
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
    """Read one source of bytes: live draft for preflight, receipt archive for acceptance."""
    def __init__(self, root):
        self.root, self.contents = root, {}

    def read(self, name):
        if not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Invalid submitted input path')
        if name not in self.contents:
            self.contents[name] = draft_bytes(self.root, name)
        return self.contents[name].decode('utf-8')

    def json(self, name):
        return json.loads(self.read(name))

    def retain(self, archive):
        for name, data in self.contents.items():
            saved = archive / 'inputs' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            with saved.open('xb') as stream:stream.write(data)


def submission_files(submission):
    """Only explicit product fields declare dependencies; file contents declare no more."""
    mapped = submission.candidate if isinstance(submission,CheckSubmission) and submission.candidate else submission
    paths = [submission.map_path, mapped.map_path]
    if isinstance(submission,(CheckSubmission,ExploreSubmission)):
        paths += [submission.harness_path,*submission.files.values()]
        if isinstance(submission,CheckSubmission):paths.append(submission.plan_path)
    return dict.fromkeys(path for path in paths if path)


def retain_receipt(draft, archive, result):
    # An existing receipt, even incomplete after interruption, never falls back to mutable draft bytes.
    if archive.exists():return
    archive.mkdir(parents=True)
    inputs, errors = Inputs(draft), []
    name = result.get('submission')
    try:
        submission = AuditSubmission.model_validate(inputs.json(name))
        for path in submission_files(submission):
            try:inputs.read(path)
            except (OSError,ValueError,TypeError) as exc:errors.extend(submission_diagnostics(exc))
    except (OSError,ValueError,KeyError,TypeError) as exc:errors.extend(submission_diagnostics(exc))
    finally:
        if isinstance(name,str) and name in inputs.contents:(archive/'raw.json').write_bytes(inputs.contents[name])
        inputs.retain(archive)
    if errors:write_json(archive/'diagnostics.json',submission_errors(errors,archive,result))


def harness_files(inputs, submission, raw):
    if raw.get("source") or raw.get("files"):
        raise ValueError("Harness content must come from separate submitted files")
    raw["source"] = inputs.read(submission.harness_path)
    raw["files"] = {name: inputs.read(path) for name, path in submission.files.items()}


def add_support(implementation, harness):
    support = getattr(implementation, 'support_files', lambda:{})()
    if set(support) & set(harness.files):raise ValueError('Submitted files cannot replace selected backend support')
    harness.files.update(support)


def prepare_harness(engine, harness):
    source = getattr(engine, 'source_root', engine.root / 'source')
    add_support(engine.implementation, harness)
    filename = engine.implementation.resolve_harness(harness, source, engine.state.snapshot.files)
    install_harness(source, filename, harness, engine.state.snapshot.files, write=False)
    return filename


def plan_from_files(inputs, submission, unit):
    raw = inputs.json(submission.plan_path)
    harness_files(inputs, submission, raw["harness"])
    plan = DirectCheckPlan.model_validate(raw)
    plan.claim_id = plan.claim_id or unit.obligation_ids[0]
    plan.binding_ids = plan.binding_ids or list(unit.binding_ids)
    return plan


def require_unit(state, id):
    unit = next((u for u in state.units if u.status != 'revised' and (u.id == id or u.candidate_id == id)), None)
    if unit is None:
        raise ValueError("Select an accepted audit unit")
    return unit


def resolve_question(state, submission):
    current = next((c for c in state.question_candidates if c.id == submission.candidate_id), None)
    if submission.candidate_id and current is None:
        raise ValueError('Candidate ID must name a saved investigation')
    changes = submission.question
    if isinstance(changes, AuditQuestion):changes = changes.model_dump(exclude_unset=True)
    value = current.question.model_dump() if current else {}
    value.update(changes or {})
    submission.question = AuditQuestion.model_validate(value)


def candidate(engine, submission, operation_id, spec=None):
    state = engine.state
    current = next((c for c in state.question_candidates if c.id == submission.candidate_id), None)
    parent = next((c for c in state.question_candidates if c.id == submission.parent_candidate_id), None)
    if submission.parent_candidate_id and parent is None:
        raise ValueError('Parent ID must name a saved investigation')
    q = submission.question
    validate_question(q)
    known = {m.id for m in state.materials}
    if not set(q.source_ids) <= known or not any(
            m.id in q.source_ids and m.file in state.snapshot.files for m in state.materials):
        raise ValueError('Question needs actual authorized source citations')
    from .audit_spec import require_basis
    require_basis(state, q, spec, candidate_id=current.id if current else None)
    if parent and q == parent.question:
        raise ValueError('A child needs a distinct sourced question')
    if submission.action == 'explained' and (not q.counterevidence or q.disposition != 'explained_by_existing_mechanism'):
        raise ValueError('Explained disposition needs scoped sourced counterevidence')
    if current:
        from .research import source_refs
        if ((not set(current.question.counterevidence) <= set(q.counterevidence) or
                not set(current.question.unknowns) <= set(q.unknowns)) and
                not (submission.feedback and source_refs(state, submission.feedback.ref_ids))):
            raise ValueError('Use sourced feedback to explain changed counterevidence or unknowns')
        if current.question != q:
            current.history.append(current.question.model_copy(deep=True))
            current.version += 1
        current.question = q
    else:
        current = QuestionCandidate(question=q, parent_candidate_id=parent.id if parent else None)
        state.question_candidates.append(current)
    current.check_ids.append(operation_id)
    current.status = {'continue':'active', 'pause':'paused', 'explained':'explained', 'obligation':'escalated'}[submission.action]
    current.stop_reason = submission.rationale
    current.resume_conditions = submission.resume_conditions
    unit = next((u for u in state.units if u.candidate_id == current.id and u.status != 'revised'), None)
    state.active_unit_id = unit.id if unit and submission.action not in {'pause','explained'} else None
    state.active_direct_check_id = None
    if submission.action == 'obligation':
        if current.obligation_id:
            raise ValueError('Use revise_check to change an accepted obligation and execute its successor')
        from .graph import apply_patch
        claim = submission.obligation
        for binding in submission.bindings:
            if not binding.associations:
                binding.associations = [BindingAssociation(claim_id=claim.id,
                    source_ids=[binding.material_id], rationale=binding.description)]
        unit = UnitDraft(id='unit-' + claim.id, candidate_id=current.id, obligation_ids=[claim.id],
            binding_ids=[b.id for b in submission.bindings], scope=claim.scope,
            rationale=submission.rationale, audit_question=q)
        if claim.id in {c.id for c in state.claims}:
            raise ValueError('New obligation ID already exists; use its current Unit for revisions')
        apply_patch(state, GraphPatch(claims=[claim], bindings=submission.bindings, units=[unit],
            rationale=submission.rationale), audit_spec=spec)
        current.obligation_id = claim.id
        state.active_unit_id = unit.id
    return current


def accept(engine, submission, inputs, operation_id):
    """Persist only after the shared preparation has validated the whole product."""
    prepare_submission(engine, submission, inputs, operation_id)()


def prepare_submission(engine, submission, inputs, operation_id):
    """Validate on a transaction's state copy; defer every artifact/map write."""
    from .research import global_stop
    if isinstance(submission, CheckSubmission) and submission.candidate:
        inner = submission.candidate
        merged = {}
        for key in ('feedback', 'review', 'map_path', 'map_changes', 'repair_of'):
            outer_value, inner_value = getattr(submission, key), getattr(inner, key)
            if outer_value and inner_value and outer_value != inner_value:
                raise ValueError('Combined submission has conflicting ' + key)
            merged[key] = outer_value or inner_value
        submission = submission.model_copy(update={**merged,
            'candidate':inner.model_copy(update=merged)})
    state = engine.state
    research_before = state.model_copy(update={name:[o.model_copy(deep=True) for o in getattr(state,name)]
        for name in ('question_candidates','claims','bindings','relations','units','direct_checks','semantic_reviews','review_issues')})
    mapped=submission.candidate if isinstance(submission,CheckSubmission) and submission.candidate else submission
    from . import audit_spec
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    spec=audit_spec.load(state)
    proposed=None
    issues=[]
    references = submission.sources + (mapped.sources if mapped is not submission else [])
    state.materials.extend(source_materials(engine, references, issues,
        ['/sources/'+str(i) for i in range(len(submission.sources))]+
        (['/candidate/sources/'+str(i) for i in range(len(mapped.sources))] if mapped is not submission else [])))
    unavailable = {ref.id for ref in references} - {m.id for m in state.materials}
    def collect_validation(check):
        try:check()
        except ValueError as exc:
            issues.extend(getattr(exc,'diagnostics',None) or [Diagnostic(code='submission',category='semantic',message=str(exc))])
    changes=getattr(mapped,'map_changes',{})
    if getattr(mapped,'map_path',None):
        proposed=ConsensusAuditSpec.model_validate(inputs.json(mapped.map_path))
        collect_validation(lambda:audit_spec.validate(state,proposed,changes,unavailable))
        if audit_spec.map_delta(spec,proposed):
            spec=proposed.model_copy(deep=True)
            spec.version=state.audit_spec_version+1
    elif changes:raise ValueError('Map change declarations require a complete map file')
    def question_version(q, candidate_id=None):
        if not any((q.behavior_ids, q.fact_ids, q.activity_classes, q.supporting_behavior_ids)):
            return
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
    if isinstance(mapped,CandidateSubmission):
        resolve_question(state, mapped)
        collect_validation(lambda:question_version(mapped.question,mapped.candidate_id))
        collect_validation(lambda:validate_question(mapped.question))
        if spec and mapped.question.audit_spec_version==spec.version:
            collect_validation(lambda:audit_spec.validate_question(spec,mapped.question,engine.config.activity_focus))
        missing=set(mapped.question.source_ids)-{m.id for m in state.materials}-unavailable
        if missing:issues.append(Diagnostic(code='question_sources',category='material',message='Question has unacquired sources: '+', '.join(sorted(missing))))
        if mapped.obligation and not unavailable.intersection(mapped.obligation.grounding.source_ids + mapped.obligation.grounding.expectation_ids):
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
        audit_spec.validate_units(state, spec)
    if submission.review:
        from .reviews import accept_review
        accept_review(state, submission.review, operation_id)
    current = {"phase":"accepted", "operation_id":operation_id, "action":submission.action}
    persist_artifact = lambda: None
    if isinstance(submission, CandidateSubmission):
        candidate(engine, submission, operation_id, spec)
    elif isinstance(submission, CheckSubmission):
        require_capacity(engine, 'experiments')
        if not engine.config.allow_experiments:
            raise ValueError('Formal execution is not authorized')
        if submission.candidate:candidate(engine, submission.candidate, operation_id, spec)
        unit = require_unit(state, submission.unit_id or 'unit-' + submission.candidate.obligation.id)
        prior = next((a for a in state.direct_checks if a.id == submission.previous_check_id), None)
        if submission.previous_check_id:
            if prior is None or prior.unit_id != unit.id:
                raise ValueError('Previous check must belong to the same selected Unit')
            if any(a.previous_id == prior.id for a in state.direct_checks):
                raise ValueError('Previous check already has a successor; revise the current artifact')
        changed = []
        if submission.revision:
            from .graph import apply_patch
            from .mutations import write_set
            from .direct_checks import semantic_ids
            patch = submission.revision
            writes = write_set(state, patch)
            if not {id for id, field in writes} <= semantic_ids(state, unit):
                raise ValueError('Revision changes an unrelated investigation; submit its own successor')
            changed = [{'object_id':id, 'field':field} for id, field in writes]
            for draft in patch.units:
                if draft.candidate_id != unit.candidate_id or draft.id != unit.id:
                    raise ValueError('Revision retains its investigation identity; use a linked Candidate for a different question')
                if draft.audit_question:question_version(draft.audit_question, unit.candidate_id)
            patch.rationale = submission.rationale
            apply_patch(state, patch, semantic=True, audit_spec=spec)
            unit = require_unit(state, unit.id)
            reconnect_candidate(state, unit)
        plan = plan_from_files(inputs, submission, unit)
        validate_plan(state, unit, plan, engine.implementation)
        filename = prepare_harness(engine, plan.harness)
        validate_objects()
        def persist_artifact():
            artifact = save_plan(engine, unit, plan, operation_id, prior, filename=filename)
            if prior:
                old = load_plan(prior.plan_path).model_dump(mode='json')
                new = plan.model_dump(mode='json')
                state.revisions.append(Revision(rationale=submission.rationale, target_ids=[prior.id],
                    evidence_ids=[c.id for c in state.checks if c.direct_check_id == prior.id],
                    before={'direct_check_id':prior.id, 'graph_versions':prior.graph_versions},
                    after={'direct_check_id':artifact.id, 'graph_versions':artifact.graph_versions,
                        'changed_plan_fields':[key for key in old if old[key] != new[key]], 'graph_changes':changed}))
            current['direct_check_id'] = artifact.id
            state.active_unit_id, state.active_direct_check_id = unit.id, artifact.id
    elif isinstance(submission, ResearchSubmission):
        pass
    elif isinstance(submission, ExploreSubmission):
        require_capacity(engine,'experiments')
        if not engine.config.allow_experiments or engine.implementation is None:
            raise ValueError("Exploratory execution is not authorized or configured")
        harness = Harness(kind=engine.implementation.harness_kind, source=inputs.read(submission.harness_path),
            execution_package=submission.execution_package,
            files={name:inputs.read(path) for name, path in submission.files.items()},
            description=submission.question, semantic_changes=[])
        current['harness_filename'] = prepare_harness(engine, harness)
        current["harness"] = harness.model_dump(mode="json")
    else:
        current.update(scope=submission.scope,reason=submission.reason)
        if global_stop(current):
            state.stop_reason = f"Scoped stop ({submission.scope}/{submission.reason}): " + submission.rationale
    if submission.feedback:
        for id,update in submission.feedback.question_updates.items():
            c=next(c for c in state.question_candidates if c.id==id)
            if update.resume_conditions and c.status!='paused':raise ValueError('Feedback resume_conditions require a paused Candidate')
            if c.question.unknowns!=update.unknowns:
                c.history.append(c.question.model_copy(deep=True))
                c.version += 1
            c.question.unknowns=list(update.unknowns)
            c.resume_conditions=list(update.resume_conditions)
            for unit in state.units:
                if unit.candidate_id==id and unit.status!='revised':unit.audit_question.unknowns=list(update.unknowns)
    # Forced/resource exits are always possible, even with incomplete historical understanding.
    if submission.action != 'stop':validate_objects()
    def finish():
        persist_artifact()
        refresh_assessments(state, {a.id for a in state.direct_checks}, before=research_before)
        sync_progress(engine)
        if proposed is not None:audit_spec.accept(engine,proposed)
        decision=state.selections[-1]
        decision['candidate_ids']=list(dict.fromkeys(decision.get('candidate_ids',[])+[c.id for c in state.question_candidates if operation_id in c.check_ids]))
        decision['accepted_versions']={'audit_spec':state.audit_spec_version,'graph':state.graph_version,
            'units':{u.id:u.version for u in state.units if u not in research_before.units},
            'artifacts':{a.id:a.version for a in state.direct_checks if a not in research_before.direct_checks}}
        if submission.action=='explained':
            units=[u for u in state.units if u.candidate_id in decision['candidate_ids'] and u.status!='revised']
            for kind,ids in {'units':[u.id for u in units], 'claims':[id for u in units for id in u.obligation_ids],
                    'bindings':[id for u in units for id in u.binding_ids], 'relations':[id for u in units for id in u.relation_ids]}.items():
                decision['accepted_versions'][kind]={obj.id:obj.version for obj in getattr(state,kind) if obj.id in ids}
        state.current_submission = current

    return finish

def require_capacity(engine, resource, amount=1):
    available=getattr(engine.config.budget,resource)-engine.state.usage.get(resource,0)
    if available<amount:
        raise ValueError(f'Local capability unavailable: {resource} needs {amount}, remaining {available}; choose source investigation or another authorized action')


def submission_diagnostics(exc):
    from consensus_assurance.core.diagnostics import Diagnostic
    if hasattr(exc, 'diagnostics'):return exc.diagnostics
    if isinstance(exc, ValidationError):
        return [Diagnostic(code='submission',category='format',paths=['/'+'/'.join(map(str,e['loc']))],
            message=e['msg']) for e in exc.errors(include_url=False,include_input=False)]
    return [Diagnostic(code='submission',category='semantic' if isinstance(exc,ValueError) else 'tool',message=str(exc))]


def submission_errors(diagnostics, archive, result):
    return {'errors':[d.message for d in diagnostics], 'diagnostics':[d.model_dump(mode='json') for d in diagnostics],
        'raw_path':str(archive/'raw.json'), 'submitted_path':result.get('submission'), 'summary':result.get('summary')}


def validate_submission(state, root, name, implementation):
    """Read-only preparation; no Engine, lock, runner, receipt or persistent ID."""
    from types import SimpleNamespace
    from consensus_assurance.core.config import Config
    from .budget import BudgetTracker
    trial = state.model_copy(deep=True)
    config = Config.model_validate(trial.config)
    context = SimpleNamespace(state=trial,config=config,root=root,source_root=root/'agent-source',
        implementation=implementation,
        budget=BudgetTracker(config.budget,trial))
    result = {'valid':False,'run_id':state.id,'audit_spec_version':state.audit_spec_version,
        'elapsed_seconds':state.elapsed_seconds,'diagnostics':[],
        'meaning':'Validation against the state and bytes read; this is not acceptance, execution or evidence. '
            'elapsed_seconds is run usage at the last saved checkpoint, not live elapsed time in this turn. '
            'A valid preflight reserves no future budget; use the current turn allocation and its CheckRun for timing.'}
    try:
        context.budget.timeout()
        inputs = Inputs(root/'draft')
        raw = inputs.json(name)
        if not isinstance(raw,dict):raise ValueError('A submission must be a JSON object')
        product = AuditSubmission.model_validate(raw)
        prepare_submission(context,product,inputs,'preflight')
        result['valid'] = True
    except (OSError,ValueError,KeyError,TypeError,BudgetExhausted) as exc:
        result['diagnostics'] = [d.model_dump(mode='json') for d in submission_diagnostics(exc)]
    return result


def reconnect_candidate(state,unit):
    """Retain the earlier question when a check revision changes its accepted basis."""
    c=next((c for c in state.question_candidates if c.id==unit.candidate_id),None)
    if c and unit.audit_question and c.question!=unit.audit_question:
        c.history.append(c.question.model_copy(deep=True))
        c.version += 1
        c.question=unit.audit_question.model_copy(deep=True)


def method_text(kind='audit'):
    from importlib.resources import files
    from .prompts import loaded_resources
    root = files("consensus_assurance").joinpath("resources")
    paths = loaded_resources(kind)["paths"]
    return paths, "\n".join(root.joinpath(p).read_text() for p in paths)


def prompt(engine, method):
    from .research import operation_summary
    return (method + "\nRead this run's research index at " + str(engine.root / "research.json") +
        ". Submit using " + str(engine.root / "submission.schema.json") +
        "; return its path relative to the draft directory and a summary.\n" +
        ("Attributed protocol knowledge (data):\n" + engine.knowledge if method else "") +
        "\nLast operation (controller records):\n" + json.dumps(operation_summary(engine.state)))


def sync_progress(engine):
    from .direct_checks import obligation_progress, coverage_limitations
    state = engine.state
    for unit in state.units:
        if unit.status == "revised":
            continue
        unit.obligation_checks, unit.remaining_obligation_ids = obligation_progress(state, unit)
        unit.coverage_limitations = coverage_limitations(state, unit)
        unit.status = "checked" if unit.obligation_ids and not unit.remaining_obligation_ids else "partial" if unit.obligation_checks else "pending"


def execute_check(engine, artifact):
    if hasattr(engine.implementation,'validate_builds'):
        engine.implementation.validate_builds(engine.root,engine.state.snapshot.id,engine.runner.deadline)
    existing = next((c for c in engine.state.checks if c.direct_check_id == artifact.id), None)
    check = existing or execute_direct_check(engine, artifact)
    unit = require_unit(engine.state, artifact.unit_id)
    result = assess(engine.state, unit, artifact, load_plan(artifact.plan_path), check, extract_events(check))
    write_json(engine.root / "direct-checks" / artifact.operation_id / (check.id + "-assessment.json"), result)
    return check


def execute_accepted(engine):
    current, state = engine.state.current_submission, engine.state
    try:
        if current.get("direct_check_id"):
            execute_check(engine, next(a for a in state.direct_checks if a.id == current["direct_check_id"]))
        if current.get("harness"):
            def run():
                return execute_harness(engine, Harness.model_validate(current['harness']),
                    current['harness_filename'], 'exploration')
            check = CheckRun.model_validate(engine.action("exploration", "experiments", run,
                {"operation_id":current["operation_id"], 'execution_package':current['harness']['execution_package'],
                 'harness_filename':current['harness_filename']}))
            engine.record(check)
    except (OSError, ValueError, Blocked, BudgetExhausted) as exc:
        current["execution_gap"] = str(exc)
        state.gaps.append("Accepted operation execution failed: " + str(exc))
        if isinstance(exc,BudgetExhausted) and engine.budget.remaining()<=0:
            current['phase']='accepted'
            engine.checkpoint('audit_execution_deferred_at_deadline')
            return
    current["phase"] = "executed"
    sync_progress(engine)
    engine.checkpoint("audit_execution_completed")


def source_materials(engine, references, issues=None, paths=None):
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    state = engine.state
    root = getattr(engine, 'source_root', engine.root / 'source')
    # Authorize all paths before reading any requested source.
    for ref in references:
        if ref.file not in (state.snapshot.readable_files or []):
            raise ValueError('Source citation is outside the authorized snapshot: ' + ref.file)
        draft_file(root, ref.file)
    errors, additions = [], []
    existing = {m.id:m for m in state.materials}
    seen = set()
    for index, ref in enumerate(references):
        message = None
        data = draft_bytes(root, ref.file)
        if digest(data) != state.snapshot.files[ref.file]:
            message = 'Source snapshot version changed: ' + ref.file
        lines = data.decode('utf-8').splitlines()
        if message is None and (ref.end_line < ref.start_line or ref.end_line > len(lines)):
            message = 'Source citation range does not exist: ' + ref.id
        if ref.id in seen:message = 'Duplicate source range IDs: ' + ref.id
        seen.add(ref.id)
        material = Material(id=ref.id,file=ref.file,start_line=ref.start_line,end_line=ref.end_line,
            kind=ref.kind,text='\n'.join(lines[ref.start_line-1:ref.end_line]),content_digest=state.snapshot.files[ref.file])
        if message is None and ref.id in existing and existing[ref.id] != material:
            message = 'Source range ID reused for a different excerpt: ' + ref.id
        if message:
            errors.append(Diagnostic(code='source_range',category='material',object_ids=[ref.id],
                paths=[paths[index] if paths else '/sources/'+str(index)],message=message,
                details={'blocked_checks':'Checks requiring this excerpt await valid source bytes'},allowed=['read','representation']))
        elif ref.id not in existing:
            additions.append(material);existing[ref.id] = material
    if issues is not None:issues.extend(errors)
    elif errors:raise DiagnosticError(errors)
    return additions


def prepare_agent_source(engine):
    """Expose only configured readable files; the complete source remains for trusted execution."""
    source=engine.root/"source"
    view=engine.root/"agent-source"
    allowed=set(engine.state.snapshot.readable_files or [])
    if not allowed:
        raise ValueError("No source files are authorized for Codex browsing")
    for name in allowed:
        path=source/name
        if name not in engine.state.snapshot.files or not path.is_file() or digest(path.read_bytes())!=engine.state.snapshot.files[name]:
            raise ValueError("Authorized source cannot be reconstructed from the captured snapshot")
    if view.exists():
        actual={str(path.relative_to(view)) for path in view.rglob("*") if path.is_file()}
        if actual!=allowed or any(path.is_symlink() for path in view.rglob("*")):
            raise ValueError("Agent source view changed since it was captured")
        if any(digest((view/name).read_bytes())!=engine.state.snapshot.files[name] for name in allowed):
            raise ValueError("Agent source view content changed")
        return
    for name in allowed:
        target=view/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((source/name).read_bytes())


def receive(engine, payload):
    check = CheckRun.model_validate(payload[0])
    session, result = payload[1:]
    if check.status == ExecutionStatus.COMPLETED and result:
        retain_receipt(engine.root/'draft',engine.root/'submissions'/check.id,result)
    engine.record(check)
    state = engine.state
    if session:
        state.agent_session_id = session
    if not any(t['check_id'] == check.id for t in state.agent_turns):
        state.agent_turns.append({'check_id':check.id, 'session_id':session,
            'tool_events':check.parameters.get('agent_tool_events'), 'usage':check.parameters.get('agent_usage')})
    state.current_submission = {'phase':'received', 'operation_id':check.id, 'result':result,
        'status':check.status.value, 'reason':check.reason,
        'session_unavailable':check.parameters.get('agent_session_unavailable', False)}
    engine.checkpoint('agent_receipt_saved')


def accept_received(engine):
    current, state = engine.state.current_submission, engine.state
    operation_id = current['operation_id']
    result = current.get('result')
    archive = engine.root / 'submissions' / operation_id
    if current['status'] != ExecutionStatus.COMPLETED.value or not result:
        if current.get('session_unavailable'):
            state.agent_session_id = None
            state.gaps.append('Agent session unavailable; continue from saved research in a new session')
            current['phase'] = 'rejected'
            engine.checkpoint('agent_session_unavailable')
            return False
        state.stop_reason = 'Agent stopped: ' + current['reason']
        current['phase'] = 'failed'
        return False
    raw={}
    engine.budget.timeout()
    try:
        raw_path = archive/'raw.json'
        if raw_path.exists():raw = json.loads(raw_path.read_bytes())
        saved_errors = archive/'diagnostics.json'
        if saved_errors.exists():
            from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
            raise DiagnosticError([Diagnostic.model_validate(d) for d in json.loads(saved_errors.read_text())['diagnostics']])
        if not raw_path.exists():raise ValueError('Reliable receipt has no retained product bytes')
        if not isinstance(raw,dict):raise ValueError('A submission must be a JSON object')
        submission = AuditSubmission.model_validate(raw)
        inputs = Inputs(archive/'inputs')
        commit_graph(engine, 'submission-' + operation_id, submission.model_dump(mode='json'),
            lambda proxy:accept(proxy, submission, inputs, operation_id))
        write_json(archive / 'accepted.json', submission)
        return True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = submission_errors(submission_diagnostics(exc),archive,result)
        write_json(archive / 'diagnostics.json', errors)
        from .research import reject_local
        reject_local(state,operation_id,errors,raw if isinstance(raw,dict) else {})
        state.current_submission = {'phase':'rejected', 'operation_id':operation_id, 'rejected':errors}
        engine.checkpoint('submission_rejected')
        return False


def execute(engine):
    from .research import global_stop
    engine.validate_agent_inputs()
    state = engine.state
    draft = engine.root / 'draft'
    draft.mkdir(exist_ok=True)
    paths, methods = method_text()
    for name, content in getattr(engine.implementation, 'support_files', lambda:{})().items():
        path = engine.root/'target-support'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)
    write_schemas(engine.root)
    (engine.root / 'audit-method.md').write_text(methods)
    state.method_paths = paths
    write_json(engine.root / 'submission.schema.json', AuditSubmission.model_json_schema())
    # Remaining calls govern new inference, never recovery of an already durable receipt.
    pending = state.pending_action
    if pending and pending.kind == 'agent_turn' and pending.status == 'completed':
        path = engine.root / 'actions' / pending.id / 'result.json'
        if path.exists() and state.current_submission.get('phase') not in {'received', 'accepted'}:
            payload = json.loads(path.read_text())
            if not any(t['check_id'] == payload[0]['id'] for t in state.agent_turns):
                receive(engine, payload)
    if pending and pending.kind == 'agent_turn' and pending.status == 'running' and hasattr(engine.agent, 'decode'):
        receipts = [CheckRun.model_validate_json(p.read_text()) for p in (engine.root/'logs').glob('*/check.json')]
        check = next((c for c in receipts if c.pending_action_id == pending.id and c.action == 'agent_turn' and c.ended_at), None)
        if check:
            response = engine.root/'actions'/pending.id/'agent-response.json'
            payload = engine.action('agent_turn', 'agent_calls',
                lambda:engine.agent.decode(check, response, state.agent_session_id), pending.logical_input)
            receive(engine, payload)
    stop_cause='resource_limit'
    try:
        if state.current_submission.get('phase') == 'received':
            accept_received(engine)
        if state.current_submission.get('phase') == 'accepted':
            execute_accepted(engine)
        if global_stop(state.current_submission) or state.current_submission.get('phase') == 'failed':
            return state
        if not engine.config.allow_agent_materials:
            raise Blocked('Agent source browsing is disabled; no model payload sent')
        if not engine.agent.mock and (not engine.config.allow_experiments or engine.config.execution_isolation != 'bwrap'):
            raise Blocked('Codex tool sessions require authorized isolated target execution; use plan for snapshot-only inspection')
        prepare_agent_source(engine)
        if engine.knowledge:
            pack_id = 'protocol-pack:' + engine.config.protocol
            if not any(m.id == pack_id for m in state.materials):
                state.materials.append(Material(id=pack_id, file='protocol:' + engine.config.protocol,
                    start_line=1, end_line=len(engine.knowledge.splitlines()), kind='protocol_candidate',
                    text=engine.knowledge, content_digest=digest(engine.knowledge.encode())))
        if not state.tools or not getattr(engine.agent, 'available', False):
            engine.probe_tools()
        if not getattr(engine.agent, 'available', False):
            raise Blocked('Agent capability probe failed; no model payload sent')
        if hasattr(engine.implementation,'prepare_run'):
            try:
                engine.implementation.prepare_run(engine.runner,state.snapshot.id,engine.budget.timeout(),engine.config.execution_isolation)
            except ValueError as exc:raise Blocked(str(exc)) from exc
        state.stop_reason = 'Not started'
        while engine.budget.remaining() > 0:
            pending = state.pending_action
            recovering = pending and pending.kind == 'agent_turn' and pending.status == 'running' and any(
                c.pending_action_id == pending.id and c.ended_at for c in
                (CheckRun.model_validate_json(p.read_text()) for p in (engine.root/'logs').glob('*/check.json')))
            if not recovering and state.usage.get('agent_calls', 0) >= engine.config.budget.agent_calls:
                raise BudgetExhausted('agent_calls budget exhausted; retained local work remains visible')
            request = prompt(engine, methods if not state.agent_session_id else '')
            if hasattr(engine.agent, 'prepare'):
                engine.agent.read_only_roots = engine.implementation.read_only_roots() if engine.implementation else []
                engine.agent.tool_environment = engine.implementation.environment(draft) if engine.implementation else {}
                try:permitted, checks = engine.agent.prepare(engine.runner, draft, state.snapshot.id)
                except ValueError as exc:raise Blocked(str(exc)) from exc
                for check in checks:
                    engine.record(check)
                if not permitted:
                    raise Blocked('Codex permission probe is inconclusive or denied; inspect probe logs; no model payload sent')
            payload = engine.action('agent_turn', 'agent_calls', lambda:engine.agent.investigate(
                engine.runner, request, draft, state.snapshot.id,
                engine.config.budget.agent_turn_timeout, state.agent_session_id),
                {'session_id':state.agent_session_id, 'turn':len(state.agent_turns)})
            receive(engine, payload)
            accepted = accept_received(engine)
            if state.current_submission.get('phase') == 'failed':
                break
            if accepted:
                execute_accepted(engine)
                if global_stop(state.current_submission):
                    break
    except (BudgetExhausted, Blocked) as exc:
        state.stop_reason = str(exc)
        stop_cause='resource_limit' if isinstance(exc,BudgetExhausted) else 'tool_gap'
    except KeyboardInterrupt:
        state.stop_reason='User interrupted the audit investigation; partial work retained'
        stop_cause='user_stop'
        raise
    finally:
        if state.stop_reason == 'Not started':
            state.stop_reason = 'Audit investigation reached the authorized total time budget'
        if not global_stop(state.current_submission):
            from .research import stop_record
            last = state.checks[-1] if state.checks else None
            reason = ('resource_limit' if engine.budget.remaining() <= 0
                else 'user_stop' if last and last.status == ExecutionStatus.CANCELLED
                else 'tool_gap' if state.current_submission.get('phase') == 'failed' else stop_cause)
            stop_record(engine, reason)
        engine.checkpoint('audit_stopped')
    return state


def write_schemas(root):
    products = [DirectCheckPlan, ConsensusAuditSpec, GraphPatch]
    schemas = {kind.__name__:kind.model_json_schema() for kind in products}
    write_json(root / "product-schemas.json", schemas)
