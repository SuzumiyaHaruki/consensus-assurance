"""One update envelope, one fixed executor and the retained native investigation loop."""
import json
import os
import stat
import sys
from pathlib import Path
from pydantic import ValidationError
from consensus_assurance.adapters.storage.files import digest, write_json
from consensus_assurance.core.submissions import AuditSubmission
from consensus_assurance.core.types import Material, CheckRun, ExecutionStatus
from consensus_assurance.adapters.runners.experiment import install_harness
from .budget import BudgetExhausted
from .errors import Blocked
from .transactions import commit_update


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
            try:
                self.contents[name] = draft_bytes(self.root, name)
            except (OSError, ValueError) as exc:
                from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
                raise DiagnosticError([Diagnostic(code='submitted_input', category='location',
                    details={'input_path': name, 'input_root': str(self.root),
                             'resolved_path': str(self.root / name)},
                    message=f'Cannot read submitted input {name!r} at {str(self.root / name)!r}: {exc}. '
                            'Submitted input paths are relative to the draft directory '
                            f'(input root {str(self.root)!r}).')]) from exc
        return self.contents[name].decode('utf-8')

    def json(self, name):
        return json.loads(self.read(name))

    def retain(self, archive):
        for name, data in self.contents.items():
            saved = archive / 'inputs' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            with saved.open('xb') as stream:stream.write(data)


def retain_receipt(draft, archive, result, check):
    # An existing receipt, even incomplete after interruption, never falls back to mutable draft bytes.
    if archive.exists():return
    archive.mkdir(parents=True)
    if message := check.parameters.get('agent_response_error'):
        from consensus_assurance.core.diagnostics import Diagnostic
        errors = submission_errors([Diagnostic(code='agent_response',category='format',message=message)],archive,result)
        errors['raw_path'] = check.parameters['agent_response_path']
        write_json(archive/'diagnostics.json',errors)
        return
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


def method_text(kind='audit'):
    from importlib.resources import files
    from .prompts import loaded_resources
    root = files("consensus_assurance").joinpath("resources")
    paths = loaded_resources(kind)["paths"]
    return paths, "\n".join(root.joinpath(p).read_text() for p in paths)


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
            additions.append(material)
            existing[ref.id] = material
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
    engine.phase = 'agent_turn:retain_receipt'
    check = CheckRun.model_validate(payload[0])
    session, result = payload[1:]
    if check.status == ExecutionStatus.COMPLETED and result:
        retain_receipt(engine.root/'draft',engine.root/'submissions'/check.id,result,check)
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


def execute(engine):
    try:
        return _execute(engine)
    except OSError as exc:
        # Do not turn controller storage failures into rejected model submissions,
        # or let a second failed checkpoint replace the first error.
        from .research import stop_record
        reason = f'Controller I/O failure during {engine.phase}: {exc}'
        previous = engine.last_checkpoint or 'none'
        engine.state.stop_reason = reason
        stop_record(engine, 'tool_gap')
        try:
            engine.checkpoint('audit_io_error')
        except OSError:
            pass
        print(f'{reason}; last reliable checkpoint before failure: {previous}', file=sys.stderr)
        return engine.state


def _execute(engine):
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
    stop_cause='tool_gap'
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
        if not isinstance(sys.exc_info()[1], OSError):
            if state.stop_reason == 'Not started':
                state.stop_reason = ('Audit investigation reached the authorized total time budget'
                    if engine.budget.remaining() <= 0 else 'Audit investigation stopped with retained work')
            if not global_stop(state.current_submission):
                from .research import stop_record
                last = state.checks[-1] if state.checks else None
                reason = ('resource_limit' if engine.budget.remaining() <= 0
                    else 'user_stop' if last and last.status == ExecutionStatus.CANCELLED
                    else 'tool_gap' if state.current_submission.get('phase') == 'failed' else stop_cause)
                stop_record(engine, reason)
            engine.checkpoint('audit_stopped')
    return state


def submission_files(submission):
    request = submission.experiment
    return [request.harness_path, *request.files.values()] if request else []


def submission_effects(before, state, submission, operation_id):
    """Describe actual object changes without exposing provisional object identities."""
    targets = {operation_id + '-experiment': 'experiment'}
    for name, suffix in (('investigations', 'question'), ('knowledge', 'knowledge'), ('interpretations', 'interpretation')):
        for index, change in enumerate(getattr(submission, name)):
            targets[operation_id + '-' + suffix + '-' + str(index)] = getattr(change, 'ref', None) or f'{name}[{index}]'
    effects = []
    latest = {value['investigation_id']: value for value in before['interpretations']}
    for name, requested in (('materials', submission.sources), ('knowledge', submission.knowledge),
                            ('investigations', submission.investigations or submission.gaps),
                            ('interpretations', submission.interpretations), ('experiments', submission.experiment)):
        old = {value['id']: value for value in before[name]}
        changes = []
        for record in getattr(state, name):
            value = record.model_dump(mode='json')
            previous = old.get(record.id)
            if previous == value:
                continue
            effect = {'object': 'sources' if name == 'materials' else name,
                      'action': ('append' if name == 'interpretations' else 'create') if previous is None else 'update',
                      'target': targets.get(record.id, record.id)}
            if name == 'interpretations':
                effect['investigation_id'] = targets.get(record.investigation_id, record.investigation_id)
                previous = latest.get(record.investigation_id)
                latest[record.investigation_id] = value
            if previous:
                effect['changed_fields'] = [key for key in value if key not in {'id', 'operation_id', 'version', 'revision', 'history'}
                                            and value[key] != previous[key]]
                if not effect['changed_fields'] and value.get('history') != previous.get('history'):
                    effect['changed_fields'] = ['history']
            changes.append(effect)
        effects.extend(changes)
        if requested and not changes:
            effect = {'object': 'sources' if name == 'materials' else name, 'action': 'unchanged'}
            if isinstance(requested, list):
                effect['targets'] = [getattr(item, 'id', None) or getattr(item, 'ref', None) or getattr(item, 'investigation_id', None) or f'{effect["object"]}[{index}]'
                                     for index, item in enumerate(requested)]
            effects.append(effect)
    if submission.repeat_experiment_id:
        from .experiments import artifact, fixed_experiment_locator
        effects.append({'object': 'experiments', 'action': 'repeat_execution', 'target': submission.repeat_experiment_id,
                        'fixed_experiment': fixed_experiment_locator(artifact(state, submission.repeat_experiment_id)),
                        'input_source': 'Retained fixed inputs; the current draft is not read.'})
    if submission.stop:
        effects.append({'object': 'run', 'action': 'stop', 'reason': submission.stop.reason})
    return effects


def prepare_submission(engine, submission, inputs, operation_id):
    from .knowledge import (update_knowledge, validate_knowledge_receipts, validate_receipt_references, update_questions, add_gap, interpret,
                            resolve, investigation, resolved_uses, open_gaps)
    from .experiments import validate_basis, artifact, fixed_files
    from consensus_assurance.core.types import ExperimentBasis, Harness, FixedExperiment
    state = engine.state
    if submission.repeat_experiment_id is not None and (submission.experiment or submission.stop):
        raise ValueError('repeat_experiment_id cannot be combined with experiment or stop')
    if submission.experiment or submission.repeat_experiment_id is not None:
        if not engine.config.allow_experiments or engine.implementation is None:
            raise ValueError('Target execution is not authorized or configured')
    before = state.model_dump(mode='json')
    aliases = {}
    state.materials.extend(source_materials(engine, submission.sources))
    update_knowledge(state, engine.root, submission.knowledge, operation_id, aliases)
    update_questions(state, submission.investigations, operation_id, aliases)
    for gap in submission.gaps:
        add_gap(state, resolve(gap.investigation_id, aliases), gap.question, operation_id, gap.experiment_id)
    validate_receipt_references(state, submission.knowledge, submission.interpretations, aliases)
    interpret(state, engine.root, submission.interpretations, operation_id, aliases)
    validate_knowledge_receipts(state, engine.root, submission.knowledge)
    fixed = None
    request = submission.experiment
    if request:
        owner = investigation(state, resolve(request.investigation_id, aliases))
        harness = Harness(kind=engine.implementation.harness_kind, source=inputs.read(request.harness_path),
            files={name: inputs.read(path) for name, path in request.files.items()},
            execution_package=request.execution_package, test_names=request.test_names, prerequisites=request.prerequisites,
            semantic_changes=request.semantic_changes)
        basis = ExperimentBasis(harness=harness, source_ids=request.source_ids, anchors=request.anchors,
            scope=request.scope, prefix=request.prefix, requirement=request.requirement,
            responsibility=request.responsibility, comparisons=request.comparisons,
            knowledge=resolved_uses(request.knowledge, aliases))
        validate_basis(state, basis, engine.implementation)
        filename = prepare_harness(engine, basis.harness)
        prior = artifact(state, request.previous_id) if request.previous_id else None
        if prior and prior.investigation_id != owner.id:
            raise ValueError('Revise a predecessor in the same investigation')
        configuration = {'backend': engine.config.execution_backend, 'target': engine.config.target.model_dump(mode='json'),
                         'isolation': engine.config.execution_isolation, 'tools': state.tools}
        same = next((a for a in reversed(state.experiments) if a.investigation_id == owner.id and
                     a.basis == basis and a.configuration == configuration), None)
        if same is None:
            require_capacity(engine, 'experiments')
            if prior and any(a.previous_id == prior.id for a in state.experiments):
                raise ValueError('Revise the current successor, not a retired predecessor')
            if prior and not request.revision_reason.strip():
                raise ValueError('A successor needs the reason for its actual input difference')
            new = basis.model_dump(mode='json')
            old = prior.basis.model_dump(mode='json') if prior else {}
            difference = {key: {'before': old[key], 'after': value} for key, value in new.items()
                          if prior and old[key] != value}
            fixed = FixedExperiment(id=operation_id + '-experiment', investigation_id=owner.id, basis=basis,
                snapshot_id=state.snapshot.id, configuration=configuration, harness_filename=filename,
                operation_id=operation_id, version=prior.version + 1 if prior else 1,
                previous_id=prior.id if prior else None, difference=difference, revision_reason=request.revision_reason)
            state.experiments.append(fixed)
    if submission.repeat_experiment_id is not None:
        fixed = artifact(state, submission.repeat_experiment_id)
        fixed_files(engine.root, fixed)
        require_capacity(engine, 'experiments')
    if submission.stop:
        if submission.stop.reason != 'bounded_completed' or not engine.config.directed_question:
            raise ValueError('An open audit continues useful investigation until controller limits or actual interruption')
        if not state.investigations or any(i.disposition not in {'explained','closed'} or open_gaps(state,i.id) for i in state.investigations):
            raise ValueError('Directed completion requires answered questions and necessary gaps')
        successors = {a.previous_id for a in state.experiments}
        for a in state.experiments:
            if a.id in successors:
                continue
            checks = [c for c in state.checks if c.experiment_id == a.id]
            if not checks or not any(i.experiment_id == a.id for i in state.interpretations):
                raise ValueError('Directed completion retains unfinished execution or interpretation work')
        state.stop_reason = 'Scoped stop (run/bounded_completed): ' + submission.stop.rationale
        state.run_stop = {'reason':'bounded_completed', 'origin':'agent', 'operation_id':operation_id,
                          'rationale':submission.stop.rationale}
    changed = any(before[name] != state.model_dump(mode='json')[name]
                  for name in ('materials','investigations','knowledge','experiments','interpretations','run_stop'))
    current = {'phase':'accepted', 'operation_id':operation_id, 'action':'update',
               'no_change':not changed and submission.repeat_experiment_id is None, 'references':aliases,
               'effects':submission_effects(before, state, submission, operation_id)}
    if fixed:
        current['experiment_id'] = fixed.id
    if submission.stop:
        current.update(action='stop', scope='run', reason=submission.stop.reason)
    state.current_submission = current

    def persist():
        if fixed and submission.repeat_experiment_id is None:
            fixed_files(engine.root, fixed, write=True)
    return persist


def accept_received(engine):
    current = engine.state.current_submission
    operation_id = current['operation_id']
    result = current.get('result')
    archive = engine.root / 'submissions' / operation_id
    if current['status'] != ExecutionStatus.COMPLETED.value or not result:
        check = next((c for c in engine.state.checks if c.id == operation_id), None)
        if (check and check.action == 'agent_turn' and check.status == ExecutionStatus.TIMEOUT
                and check.parameters.get('timeout_limit') == 'agent_turn_timeout'
                and check.parameters.get('agent_diagnostic',{}).get('message') == ''
                and not check.parameters.get('agent_session_unavailable')
                and engine.state.agent_session_id
                and check.parameters.get('agent_session_id') == engine.state.agent_session_id):
            # Retain the interrupted receipt, never accept its draft. The normal loop
            # checks remaining capacity and permissions before a charged same-session turn.
            engine.state.current_submission = {}
            engine.advance('agent_turn_timeout:' + check.id)
            return False
        engine.state.stop_reason = 'Agent stopped: ' + current['reason']
        current['phase'] = 'failed'
        return False
    try:
        engine.budget.timeout()
        if (archive / 'diagnostics.json').exists():
            errors = json.loads((archive / 'diagnostics.json').read_text())
        else:
            product = AuditSubmission.model_validate_json((archive / 'raw.json').read_text())
            inputs = Inputs(archive / 'inputs')
            engine.phase = 'submission:commit_update'
            commit_update(engine, 'submission-' + operation_id, product.model_dump(mode='json'),
                          lambda proxy: prepare_submission(proxy, product, inputs, operation_id)())
            engine.phase = 'submission:save_acceptance'
            write_json(archive / 'accepted.json', product)
            return True
    except (ValueError, KeyError, TypeError) as exc:
        errors = submission_errors(submission_diagnostics(exc), archive, result)
        write_json(archive / 'diagnostics.json', errors)
    engine.state.current_submission = {'phase':'rejected', 'operation_id':operation_id, 'rejected':errors}
    engine.checkpoint('submission_rejected')
    return False


def execute_accepted(engine):
    from .experiments import artifact, execute
    current = engine.state.current_submission
    check = None
    if current.get('experiment_id'):
        fixed = artifact(engine.state, current['experiment_id'])
        try:
            check = execute(engine, fixed, current['operation_id'])
        except (ValueError, Blocked, BudgetExhausted) as exc:
            check = None
            current['execution_gap'] = str(exc)
            if isinstance(exc, BudgetExhausted) and engine.budget.remaining() <= 0:
                engine.checkpoint('execution_deferred_at_deadline')
                return
    current['phase'] = 'executed'
    engine.checkpoint('audit_execution_completed')
    if (check and (check.ended_at or check.parameters.get('preparation_failure'))
            and check.parameters.get('changed_target_files') is not None
            and hasattr(engine.implementation, 'cleanup')):
        engine.phase = 'experiment_execute:cleanup'
        try:
            engine.implementation.cleanup(Path(check.cwd))
        except (OSError, ValueError) as exc:
            message = f'Private build cleanup incomplete for {check.id}: {exc}; saved execution is unchanged'
            engine.state.gaps.append(message)
            print(message, file=sys.stderr)


def validate_submission(state, root, name, implementation):
    from types import SimpleNamespace
    from consensus_assurance.core.config import Config
    from .budget import BudgetTracker
    trial = state.model_copy(deep=True)
    config = Config.model_validate(trial.config)
    context = SimpleNamespace(state=trial, config=config, root=root, source_root=root / 'agent-source',
                              implementation=implementation, budget=BudgetTracker(config.budget, trial))
    result = {'valid':False, 'run_id':state.id, 'elapsed_seconds':state.elapsed_seconds, 'diagnostics':[],
              'meaning':'Read-only validation of these bytes and saved state; no acceptance, execution or budget reservation'}
    try:
        context.budget.timeout()
        inputs = Inputs(root / 'draft')
        product = AuditSubmission.model_validate(inputs.json(name))
        prepare_submission(context, product, inputs, 'preflight')
        result.update(valid=True, no_change=trial.current_submission['no_change'],
                      execution_requested=bool(trial.current_submission.get('experiment_id')),
                      effects=trial.current_submission['effects'])
    except (OSError, ValueError, KeyError, TypeError, BudgetExhausted) as exc:
        result['diagnostics'] = [d.model_dump(mode='json') for d in submission_diagnostics(exc)]
    return result


def prompt(engine, method):
    from .research import operation_summary
    return (method + '\nConsult relevant entries in the current research index at ' + str(engine.root / 'research.json') +
            '; previews point to full records in state.json. Use the small update example as needed. Consult only relevant $defs in ' +
            str(engine.root / 'submission.schema.json') + '; no full-schema reading prerequisite.\n' +
            '\nCurrent work (controller records):\n' + json.dumps(operation_summary(engine.state, engine.root)))
