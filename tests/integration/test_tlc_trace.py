import json
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import Bundle
from consensus_assurance.core.types import ExecutionStatus, Origin
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.adapters.runners.experiment import run_experiment
from consensus_assurance.adapters.verifiers.trace import project
from consensus_assurance.adapters.runners.python import PythonBackend


@pytest.mark.real
@pytest.mark.parametrize("negative", [False, True])
def test_real_tlc_positive_and_counterexample(tlc, prepared, negative):
    verifier, runner = tlc
    _, state, bundle, _ = prepared
    if negative:
        bundle.properties = bundle.properties.replace("value <= 3", "value <= 2")
    model = save_bundle(runner.root, state, state.units[0], bundle, PythonBackend())
    result = verifier.check(runner, model, 20)
    assert result.status == ExecutionStatus.COMPLETED, Path(result.stdout).read_text() + Path(result.stderr).read_text()
    assert result.outcome == ("counterexample" if negative else "holds")
    if negative:
        assert result.exit_code != 0
    assert result.search_statistics


@pytest.mark.real
@pytest.mark.parametrize("incorrect", [False, True])
def test_real_code_trace_calibration(tlc, prepared, incorrect):
    verifier, runner = tlc
    repo, state, bundle, _ = prepared
    model = save_bundle(runner.root, state, state.units[0], bundle, PythonBackend())
    import shutil
    workspace = runner.root / "workspace"
    shutil.copytree(repo, workspace)
    # An explicitly labeled mutation provides an actual executable mismatch, not a fabricated log.
    if incorrect:
        (workspace / "counter.py").write_text("def step(value, limit):\n    return value + 2 if value < limit else 0\n")
    (workspace / "assurance_generated.py").write_text(bundle.harness.source)
    check = run_experiment(runner, PythonBackend().experiment_command(), workspace, state.snapshot.id, 20, "bwrap")
    check.origin = Origin.MUTATION if incorrect else Origin.EXECUTED
    calibration, checks = verifier.calibrate(runner, model, bundle, check, 20)
    assert calibration.status == ("incompatible" if incorrect else "compatible"), calibration.reason
    assert checks and checks[0].action == "trace_calibration"


def test_missing_observation_is_inconclusive(prepared):
    _, _, bundle, _ = prepared
    with pytest.raises(ValueError, match="Key observation"):
        project([{"event":"initial","state":{}},{"event":"step","state":{"value":1}}], bundle.observation)


def test_model_property_not_a_transition_guard(prepared, tmp_path):
    _, state, bundle, _ = prepared
    bundle.behavior = bundle.behavior.replace("Next ==", "Next == Safe /\\")
    with pytest.raises(ValueError, match="separate"):
        save_bundle(tmp_path, state, state.units[0], bundle, PythonBackend())


@pytest.mark.real
def test_initial_state_counterexample_is_not_tool_error(tlc, prepared):
    verifier, runner = tlc
    _, state, bundle, _ = prepared
    bundle.properties = bundle.properties.replace("value <= 3", "value > 0")
    model = save_bundle(runner.root, state, state.units[0], bundle, PythonBackend())
    result = verifier.check(runner, model, 20)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.outcome == "counterexample"


@pytest.mark.real
def test_F1_repaired_behavior_recalibrates_same_property(tlc, prepared):
    from consensus_assurance.workflow.feedback import apply_feedback
    from consensus_assurance.core.proposals import Feedback
    import shutil
    verifier, runner = tlc
    repo, state, correct, _ = prepared
    incorrect = correct.model_copy(deep=True)
    incorrect.behavior = incorrect.behavior.replace("value < 3", "value < 2").replace("value + 1", "value + 2").replace("value = 3", "value = 2")
    before = save_bundle(runner.root, state, state.units[0], incorrect, PythonBackend())
    workspace = runner.root / "actual"; shutil.copytree(repo, workspace)
    (workspace / "assurance_generated.py").write_text(correct.harness.source)
    experiment = run_experiment(runner, PythonBackend().experiment_command(), workspace, state.snapshot.id, 20, "bwrap")
    state.checks.append(experiment)
    calibration, checks = verifier.calibrate(runner, before, incorrect, experiment, 20)
    state.checks.extend(checks); state.calibrations.append(calibration)
    assert calibration.status == "incompatible"
    fix = Feedback(kind="F1",rationale="Observed increment is one, not two",evidence_ids=[calibration.id],target_ids=[before.id],relation_ids=[],new_basis="",graph=None,bundle=correct)
    revised = apply_feedback(state,state.units[0],incorrect,fix)
    after = save_bundle(runner.root,state,state.units[0],revised,PythonBackend(),before,"F1 correction")
    recalibration, _ = verifier.calibrate(runner,after,revised,experiment,20)
    assert recalibration.status == "compatible"
    assert before.properties == after.properties and before.id != after.id
    assert Path(before.path).exists()


@pytest.mark.real
def test_F2_normative_revision_executes_new_checker(tlc, prepared):
    from consensus_assurance.workflow.feedback import apply_feedback
    from consensus_assurance.core.proposals import Feedback, GraphDraft, GraphPatch
    verifier, runner = tlc
    _, state, correct, responses = prepared
    overstrong = correct.model_copy(deep=True)
    overstrong.properties = overstrong.properties.replace('value <= 3', 'value <= 2')
    old_model = save_bundle(runner.root, state, state.units[0], overstrong, PythonBackend())
    old_check = verifier.check(runner, old_model, 20)
    state.checks.append(old_check)
    assert old_check.outcome == 'counterexample'
    graph = GraphDraft.model_validate(responses[1])
    graph.claims[1].description = 'The documented boundary is the supplied capacity, including capacity itself'
    correction = Feedback(kind='F2',rationale='The old checker excluded the documented capacity value',evidence_ids=[next(m.id for m in state.materials if m.file=='README.md')],target_ids=['step_obligation'],relation_ids=[],new_basis='The fixture documents reaching capacity before reset; the old strict boundary was unsupported',graph=graph,bundle=None)
    correction.graph = None
    correction.patch = GraphPatch(claims=[graph.claims[1]],expected_versions={graph.claims[1].id:1},rationale=correction.new_basis)
    correction.old_judgment = state.claims[1].description
    correction.new_judgment = graph.claims[1].description
    correction.grounding = graph.claims[1].grounding.model_copy(deep=True)
    correction.grounding.unresolved = []
    from regression_support import declared_changes
    declared_changes(state,correction)
    apply_feedback(state,state.units[0],overstrong,correction)
    new_model = save_bundle(runner.root,state,state.units[0],correct,PythonBackend(),old_model,'F2 normative correction')
    new_check = verifier.check(runner,new_model,20)
    assert new_check.outcome == 'holds'
    assert Path(old_model.path).read_text() != Path(new_model.path).read_text()
    assert state.revisions[-1].kind == 'F2'


def test_F4_actual_async_order_is_checked(tmp_path):
    import sys
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.core.events import match_prerequisites
    from consensus_assurance.core.proposals import EventRequirement, Comparison
    runner = ProcessRunner(tmp_path)
    scripts = [
        "import threading,json; started=threading.Event();changed=threading.Event()\n"
        "def emit(e): print('CA_EVENT '+json.dumps({'event':e,'operation':'one'}),flush=True)\n"
        "def worker():\n emit('started'); started.set(); changed.wait(); emit('completed')\n"
        "thread=threading.Thread(target=worker);thread.start();started.wait();emit('context_changed');changed.set();thread.join()\n",
        "import threading,json\n"
        "def emit(e): print('CA_EVENT '+json.dumps({'event':e,'operation':'one'}),flush=True)\n"
        "def worker(): emit('started');emit('completed')\n"
        "emit('context_changed');thread=threading.Thread(target=worker);thread.start();thread.join()\n"
    ]
    outcomes = []
    requirements=[EventRequirement(alias='started',event='started'),
        EventRequirement(alias='context_changed',event='context_changed',conditions=[Comparison(field='operation',reference='started.operation')]),
        EventRequirement(alias='completed',event='completed',conditions=[Comparison(field='operation',reference='context_changed.operation')])]
    for script in scripts:
        check = runner.run([sys.executable,'-c',script],tmp_path,'experiment','fixture',5)
        assert check.exit_code == 0
        outcomes.append(match_prerequisites(extract_events(check),requirements)['status']=='matched')
    assert outcomes == [True, False]
