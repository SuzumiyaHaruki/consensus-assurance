"""Fixed inputs and finite observations; interpretations never rewrite executions."""
from pathlib import Path
import time
from consensus_assurance.core.types import FixedExperiment, FailureAttribution
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Origin, now
from consensus_assurance.core.events import event_requirements, match_prerequisites, comparison_requirements
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events, install_harness
from .observations import compare_events


def artifact(state, id):
    raw = next((a for a in state.experiments if a.id == id), None)
    if raw is None:
        raise ValueError('Unknown fixed experiment: ' + str(id))
    return FixedExperiment.model_validate(raw)


def validate_basis(state, basis, implementation):
    from .knowledge import require_sources, require_uses
    from .locations import locate
    require_sources(state, basis.source_ids)
    require_uses(state, basis.knowledge)
    if implementation is None or basis.harness.kind != implementation.harness_kind:
        raise ValueError('Unsupported experiment harness')
    materials = {m.id: m for m in state.materials}
    for anchor in basis.anchors:
        located, error = locate(anchor, materials)
        if error:
            raise ValueError(error)
        from consensus_assurance.core.types import CodeAnchor
        anchor.anchor = CodeAnchor.model_validate(located)
    if basis.requirement and (not basis.responsibility.strip() or not basis.anchors):
        raise ValueError('A requirement needs sourced applicability reasoning and verified code anchors')
    declared = event_requirements(basis.harness.prerequisites)
    for comparison in basis.comparisons:
        comparison_requirements(comparison, declared)
        conditions = comparison.applicability_conditions
        assertion = comparison.assertion
        if assertion.field in comparison.identity_fields:
            raise ValueError('Compared value cannot establish independent operation identity')
        if any(c.field == assertion.field for c in conditions):
            raise ValueError('Applicability cannot filter on the compared result')
        antecedent = comparison.antecedent
        if antecedent and (antecedent.reference or antecedent.field in comparison.identity_fields or
                any(c.field == antecedent.field for c in conditions)):
            raise ValueError('An observed antecedent cannot establish identity or applicability')


def fixed_files(root, fixed, *, write=False):
    folder = root / 'fixed-experiments' / fixed.id
    values = {fixed.harness_filename: fixed.basis.harness.source, **fixed.basis.harness.files}
    for name, value in values.items():
        path = folder / name
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_text() != value:
                raise ValueError('Retained experiment bytes changed')
            path.write_text(value)
        elif (not path.is_file() or path.is_symlink() or
                any(p.is_symlink() for p in path.parents if p.is_relative_to(root)) or path.read_text() != value):
            raise ValueError('Retained experiment bytes differ from the accepted basis')
    if write:
        write_json(folder / 'basis.json', fixed)
    else:
        from .audit import draft_bytes
        saved = FixedExperiment.model_validate_json(draft_bytes(root, str(folder.relative_to(root) / 'basis.json')))
        if saved != fixed:
            raise ValueError('Retained experiment configuration changed')


def execute(engine, fixed):
    fixed_files(engine.root, fixed)
    if fixed.snapshot_id != engine.state.snapshot.id:
        raise ValueError('Experiment source snapshot mismatch')
    current = {'backend': engine.config.execution_backend, 'target': engine.config.target.model_dump(mode='json'),
               'isolation': engine.config.execution_isolation, 'tools': engine.state.tools}
    if fixed.configuration != current:
        raise ValueError('Experiment execution configuration changed')
    for name, expected in engine.state.snapshot.files.items():
        from .audit import draft_bytes
        from consensus_assurance.adapters.storage.files import digest
        if digest(draft_bytes(engine.root / 'source', name)) != expected:
            raise ValueError('Captured source changed before execution: ' + name)

    def perform():
        started, clock = now(), time.monotonic()
        workspace = engine.workspace()
        harness = fixed.basis.harness
        paths = install_harness(workspace, fixed.harness_filename, harness, engine.state.snapshot.files)
        check = run_experiment(engine.runner,
            engine.implementation.experiment_command(harness.execution_package, fixed.harness_filename),
            workspace, fixed.snapshot_id, engine.budget.timeout(), engine.config.execution_isolation,
            'experiment', adapter=engine.implementation)
        check.experiment_id = fixed.id
        check.origin = Origin.MOCK if engine.state.mode == 'mock' else Origin.EXECUTED
        check.tool_version = engine.state.tools.get('implementation', 'unknown')
        check.parameters.update(execution_package=harness.execution_package, harness_filename=fixed.harness_filename,
                                action_started_at=started, action_seconds=time.monotonic() - clock)
        check.artifacts.extend(paths)
        if 'changed_target_files' not in check.parameters:
            after = capture(workspace, excluded_dirs={'.execution'}).files
            check.parameters['changed_target_files'] = [p for p, v in engine.state.snapshot.files.items() if after.get(p) != v]
        return check

    check = CheckRun.model_validate(engine.action('experiment_execute', 'experiments', perform,
                                                 {'experiment_id': fixed.id}))
    engine.record(check)
    return check


def observed(fixed, check, root=None):
    if root is not None:
        check = check.model_copy(update={'stdout': str(root / 'logs' / check.id / 'stdout.log')})
    events = extract_events(check)
    return {'events': events,
            'prerequisites': None if fixed.basis.comparisons else match_prerequisites(events, fixed.basis.harness.prerequisites),
            'comparisons': [compare_events(events, c, fixed.basis.harness.prerequisites, i)
                            for i, c in enumerate(fixed.basis.comparisons)],
            'parsing_errors': [e for e in events if e.get('event') == 'invalid_observation']}


def validate_failure(state, root, fixed, check, measurement, value):
    """Only a completed, intact violating witness followed by an independently explained test failure."""
    a = FailureAttribution.model_validate(value)
    if (a.check_id != check.id or check not in state.checks or check.experiment_id != fixed.id or
            check.snapshot_id != fixed.snapshot_id or fixed.snapshot_id != state.snapshot.id):
        raise ValueError('Failure attribution must identify the exact retained experiment execution')
    if (state.mode == 'mock' or check.origin != Origin.EXECUTED or check.status != ExecutionStatus.COMPLETED or
            not check.started_at or not check.ended_at or check.exit_code is None or not 0 < check.exit_code < 126 or
            check.outcome != 'tests_failed' or check.parameters.get('test_started') is False or
            check.parameters.get('failure_class') == 'build_or_setup' or
            check.parameters.get('changed_target_files') != [] or check.parameters.get('lock_unchanged') is False or
            measurement['parsing_errors']):
        raise ValueError('Failure attribution requires a completed original test failure with intact inputs and prerequisites')
    if not a.witness_indices:
        raise ValueError('Failure attribution needs exact violating event indices')
    results = measurement['comparisons']
    for index, indices in a.witness_indices.items():
        if not 0 <= index < len(results):
            raise ValueError('Unknown comparison index')
        result = results[index]
        if (not indices or len(set(indices)) != len(indices) or
                not set(indices) <= set(result['valid_witness_indices'])):
            raise ValueError('Failure attribution cites no complete violating witness')
        correlations = result['correlations']
        if any(correlations[str(i)]['alias_indices'] == correlations[str(j)]['alias_indices']
               for i in indices for j in result['evaluated_indices'] if j != i):
            raise ValueError('Competing same-operation observations cannot be selected away')
    fixed_files(root, fixed)
    stream = root / 'logs' / check.id / (a.failure_stream + '.log')
    harness = root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    for path, interval in ((stream, a.failure_lines), (harness, a.harness_lines)):
        if (path.is_symlink() or not path.is_file() or
                any(p.is_symlink() for p in path.parents if p.is_relative_to(root))):
            raise ValueError('Failure attribution file is not retained')
        lines = path.read_text().splitlines()
        start, end = interval
        if not 1 <= start <= end <= len(lines) or not any(s.strip() for s in lines[start - 1:end]):
            raise ValueError('Failure attribution line range is invalid')
    return a.witness_indices


def assessment(state, root, fixed, check):
    from .knowledge import open_gaps
    value = observed(fixed, check, root)
    interpretations = [i for i in state.interpretations if i.experiment_id == fixed.id and check.id in i.executions]
    opinion = interpretations[-1] if interpretations else None
    blockers = []
    if not fixed.basis.requirement or not fixed.basis.comparisons:
        blockers.append('Exploratory basis has no fixed requirement and comparison')
    if opinion is None:
        blockers.append('Execution has no attributed interpretation')
    elif opinion.conclusion not in {'violated', 'holds'}:
        blockers.append('Current interpretation remains conditional, disputed or unresolved')
    gaps = open_gaps(state, fixed.investigation_id, fixed.id)
    blockers.extend(g.question for g in gaps)
    if state.invalidation:
        blockers.append(state.invalidation)
    if check.status != ExecutionStatus.COMPLETED:
        blockers.append('Execution did not complete: ' + check.status.value)
    if check.experiment_id != fixed.id or check.snapshot_id != fixed.snapshot_id:
        blockers.append('Execution input association mismatch')
    try:
        fixed_files(root, fixed)
    except (OSError, ValueError) as exc:
        blockers.append(str(exc))
    if check.parameters.get('changed_target_files') or check.parameters.get('lock_unchanged') is False:
        blockers.append('Protected target or build inputs changed')
    if check.outcome == 'not_applicable':
        blockers.append('No selected test completed')
    if value['parsing_errors']:
        blockers.append('Invalid or incomplete observation output')
    if value['prerequisites'] and value['prerequisites']['status'] != 'matched':
        blockers.append(value['prerequisites']['reason'])
    attributed = {}
    if check.exit_code != 0:
        if opinion and opinion.failure_attribution:
            try:
                attributed = validate_failure(state, root, fixed, check, value, opinion.failure_attribution)
            except (ValueError, OSError) as exc:
                blockers.append(str(exc))
        if not attributed:
            blockers.append('Nonzero exit has no valid independent-failure attribution')
    original = state.mode != 'mock' and check.origin == Origin.EXECUTED
    if not original:
        blockers.append('Scripted or nonoriginal execution is framework evidence only')
    for r in value['comparisons']:
        r['confirmed'] = bool(not blockers and r['witness_complete'] and opinion.conclusion == 'violated' and
                              set(opinion.executions[check.id]) & set(r['valid_witness_indices']) and
                              (check.exit_code == 0 or r['comparison_index'] in attributed))
    complete = bool(value['comparisons']) and all(r['comparison_complete'] for r in value['comparisons'])
    agrees = opinion is not None and opinion.conclusion == (
        'violated' if any(r['outcome'] == 'violated' for r in value['comparisons']) else 'holds')
    return {**value, 'experiment_id': fixed.id, 'check_id': check.id,
            'outcome': 'violated' if any(r['outcome'] == 'violated' for r in value['comparisons']) else
                       'holds' if complete else 'unknown',
            'confirmed': any(r['confirmed'] for r in value['comparisons']),
            'reviewed_complete': complete and agrees and not blockers and check.exit_code == 0,
            'blockers': list(dict.fromkeys(blockers)), 'gap_ids': [g.id for g in gaps],
            'interpretation_id': opinion.id if opinion else None}
