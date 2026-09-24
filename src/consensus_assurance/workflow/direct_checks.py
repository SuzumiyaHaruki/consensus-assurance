"""Question routing and bounded implementation checks using existing execution evidence."""
import json
from pathlib import Path
from consensus_assurance.core.proposals import DirectCheckPlan
from consensus_assurance.core.types import DirectCheckArtifact, CheckRun, CheckerResult, Evidence, Finding, Origin, Assessment, Investigation, ExecutionStatus, uid
from consensus_assurance.core.events import match_prerequisites, event_requirements
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events, install_harness
from .errors import Blocked
from .graph_diagnostics import validate_grounding
from .observations import monitor_events


def load_plan(path):
    """Convert a legacy saved plan once at its file boundary; new plans have one schema."""
    raw=json.loads(Path(path).read_text())
    raw.pop('scope',None)
    harness=raw.get('harness',{})
    harness.pop('legal_conditions',None)
    harness.pop('observation_changes',None)
    return DirectCheckPlan.model_validate(raw)


def validate_question(question):
    if question is None or question.disposition is None:
        raise ValueError('New autonomous units need a typed question disposition')
    if question.disposition=='ready_for_check' and question.preferred_check is None:
        raise ValueError('Ready question needs preferred_check')
    if question.disposition=='needs_specific_evidence' and not question.requests and not question.unknowns:
        raise ValueError('Evidence question needs exact requests or a named discriminator in question unknowns')
    if question.preferred_check in {'direct_test','controlled_schedule'} and (not question.event_paths or not question.trigger_rationale.strip()):
        raise ValueError('Executable question needs legal event paths, observations and oracle rationale')


def validate_plan(state,unit,plan,implementation):
    errors=[]
    if plan.claim_id not in unit.obligation_ids:errors.append('Direct check must select one unit obligation')
    if not set(plan.binding_ids)<=set(unit.binding_ids):errors.append('Direct check uses nonselected bindings')
    for binding in state.bindings:
        if binding.id in plan.binding_ids and (binding.snapshot_id!=state.snapshot.id or state.snapshot.files.get(binding.file)!=binding.content_digest):
            errors.append('Direct binding does not describe the selected source snapshot: '+binding.id)
    if implementation is None or plan.harness.kind!=implementation.harness_kind:errors.append('Unsupported direct harness kind')
    if not plan.harness.prerequisites:errors.append('Direct check needs observable correlated prerequisites')
    materials={m.id:m for m in state.materials}
    for basis in [plan.harness.legality]+[m.grounding for m in plan.monitors]:
        try:validate_grounding(basis,materials,set(plan.binding_ids))
        except ValueError as exc:errors.append(str(exc))
    props={p.checker_id:p for p in plan.observable_properties}
    if len(props)!=len(plan.observable_properties) or len({m.id for m in plan.monitors})!=len(plan.monitors):errors.append('Duplicate direct property or monitor')
    if set(props)!={m.checker_id for m in plan.monitors}:errors.append('Direct property/monitor mismatch')
    for monitor in plan.monitors:
        p=props.get(monitor.checker_id)
        if p is None or p.kind not in {'event_assertion','event_implication'}:
            errors.append('Direct monitor '+monitor.id+' requires a supported shared event property')
            continue
        if (p.kind=='event_implication') != (p.antecedent is not None):
            errors.append('Direct implication needs exactly one observed antecedent')
        if not p.identity_fields:
            errors.append('Direct monitor '+monitor.id+' needs shared operation/participant/context identity')
        if not monitor.binding_ids or not set(monitor.binding_ids)<=set(plan.binding_ids):errors.append('Monitor '+monitor.id+' needs selected source bindings')
        if p.trigger.reference:errors.append('Direct trigger '+p.checker_id+' must select an actual event field')
        if p.antecedent and p.antecedent.reference:
            errors.append('Direct implication antecedent must inspect the actual result event')
        try:event_requirements(plan.harness.prerequisites,p.assertion.reference)
        except ValueError as exc:errors.append(p.checker_id+': '+str(exc))
        if p.assertion.field in p.identity_fields:
            errors.append(p.checker_id+': the compared value cannot also establish independent operation identity')
        if p.trigger.field==p.assertion.field or any(c.field==p.assertion.field for c in monitor.applicability_conditions):
            errors.append(p.checker_id+': trigger/applicability cannot filter on the result field being checked')
        if p.antecedent and (p.antecedent.field in p.identity_fields or
                p.antecedent.field==p.trigger.field or
                any(c.field==p.antecedent.field for c in monitor.applicability_conditions)):
            errors.append(p.checker_id+': implication result cannot establish identity or applicability')
    if errors:raise ValueError('; '.join(dict.fromkeys(errors)))


def save_plan(engine,unit,plan,operation_id,previous=None):
    state=engine.state
    existing=next((a for a in state.direct_checks if a.operation_id==operation_id),None)
    if existing:return existing
    folder=engine.root/'direct-checks'/operation_id
    write_json(folder/'plan.json',plan)
    harness=folder/engine.implementation.harness_filename
    harness.parent.mkdir(parents=True,exist_ok=True)
    harness.write_text(plan.harness.source)
    from .inputs import semantic_ids
    ids=semantic_ids(state,unit)
    artifact=DirectCheckArtifact(plan_path=str(folder/'plan.json'),harness_path=str(harness),
        snapshot_id=state.snapshot.id,unit_id=unit.id,claim_id=plan.claim_id,binding_ids=plan.binding_ids,
        graph_versions={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units if o.id in ids},
        origin=Origin.MOCK if state.mode=='mock' else Origin.PRESET if state.analysis_mode=='regression' else Origin.AGENT,
        scope=unit.scope,version=previous.version+1 if previous else 1,operation_id=operation_id,previous_id=previous.id if previous else None)
    state.direct_checks.append(artifact)
    return artifact


def execute(engine,artifact):
    if not engine.config.allow_experiments or engine.implementation is None:raise Blocked('Target execution disabled or no execution backend configured')
    plan=load_plan(artifact.plan_path)
    def perform():
        workspace=engine.workspace()
        before=engine.state.snapshot.files
        paths=install_harness(workspace,engine.implementation.harness_filename,plan.harness,before)
        check=run_experiment(engine.runner,engine.implementation.experiment_command(),workspace,engine.state.snapshot.id,
            engine.budget.timeout(),engine.config.execution_isolation,'direct_check',adapter=engine.implementation)
        after=capture(workspace,excluded_dirs={".execution"}).files
        changed=[p for p,value in before.items() if after.get(p)!=value]
        check.direct_check_id=artifact.id
        check.origin=Origin.MOCK if engine.state.mode=='mock' else Origin.EXECUTED
        check.parameters['changed_target_files']=changed
        check.tool_version=engine.state.tools.get('implementation','unknown')
        check.artifacts.extend(paths)
        return check
    check=CheckRun.model_validate(engine.action('direct_execute','experiments',perform,{'direct_check_id':artifact.id}))
    engine.record(check)
    return check


def compute_assessment(state,unit,artifact,plan,check,events):
    """Compute observed values and current interpretation without mutating state."""
    prerequisite=match_prerequisites(events,plan.harness.prerequisites)
    properties={p.checker_id:p for p in plan.observable_properties}
    results=[monitor_events(events,m,properties[m.checker_id],plan.harness.prerequisites) for m in plan.monitors]
    claim=next(c for c in state.claims if c.id==plan.claim_id)
    checker_ids=set(properties)
    related_artifacts=[]
    for candidate in state.direct_checks:
        if candidate.unit_id!=artifact.unit_id:continue
        try:related={m.checker_id for m in load_plan(candidate.plan_path).monitors}
        except (OSError,ValueError):related=set()
        if checker_ids&related:related_artifacts.append(candidate.id)
    blockers=[]
    versions={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units}
    if any(versions.get(id)!=version for id,version in artifact.graph_versions.items()):
        blockers.append('Direct-check semantic inputs changed; execution requires rechecking')
    reviews=[i for r in state.semantic_reviews if r.target_versions.get(artifact.id)==artifact.version
        for i in r.items if i.target_id==artifact.id and i.aspect=='checker_correspondence']
    current_review=reviews[-1] if reviews else None
    correspondence=bool(current_review and current_review.status=='no_issue_found' and not current_review.counterevidence)
    issues=[i for i in state.review_issues if i.target_id in related_artifacts and not i.resolved_by]
    if not correspondence and not issues:
        blockers.append('Direct oracle correspondence is unreviewed' if current_review is None else
            'Direct oracle correspondence remains disputed: '+current_review.rationale)
    from .reviews import issue_challenges
    blockers.extend('Open review issue '+i.id+' ['+','.join(i.source_ids)+']: '+'; '.join(issue_challenges(state,i)) for i in issues)
    if check.status==ExecutionStatus.TIMEOUT:blockers.append('External timeout; target behavior and harness completion are unestablished')
    elif check.status!=ExecutionStatus.COMPLETED:blockers.append('Execution tool or build failed: '+check.reason)
    elif check.exit_code!=0:blockers.append('Nonzero direct test exit ('+check.parameters.get('failure_class','unclassified')+'); inspect raw stack and target path before attribution')
    associated=check.snapshot_id==artifact.snapshot_id and check.direct_check_id==artifact.id
    if not associated:blockers.append('Direct input association mismatch')
    original=state.mode!='mock' and artifact.origin not in {Origin.MOCK,Origin.SYNTHETIC,Origin.MUTATION,Origin.IMPORTED} and check.origin==Origin.EXECUTED
    provenance_blockers=[] if original else ['Nonoriginal execution cannot confirm implementation']
    if prerequisite['status']!='matched':blockers.append('Correlated prerequisites not established: '+prerequisite['reason'])
    if check.parameters.get('changed_target_files'):blockers.append('Experiment changed target implementation files')
    parsing=[e.get('_ca_observation') for e in events if e.get('event')=='invalid_observation']
    if parsing:blockers.append('Event output contains incomplete or invalid CA_EVENT records')
    blockers.extend(claim.grounding.conflicts+plan.harness.legality.conflicts+
        [item for monitor in plan.monitors for item in monitor.grounding.conflicts])
    for result in results:
        local=[]
        if result['missing_indices']:local.append('Required observed fields, event identity, or prerequisite association are missing')
        if result['outcome']=='unknown' and not result['missing_indices']:local.append('No applicable result event was reached')
        result['limitations']=local
        result['comparison_complete']=result['outcome'] in {'holds','violated'} and not local
        result['confirmed']=result['outcome']=='violated' and result['comparison_complete'] and not blockers and not provenance_blockers
    execution_complete=check.status==ExecutionStatus.COMPLETED and check.exit_code==0 and associated and prerequisite['status']=='matched' and not parsing and not check.parameters.get('changed_target_files')
    bounded_complete=execution_complete and bool(results) and all(r['comparison_complete'] for r in results)
    semantic_boundaries=(current_review.limitations if current_review else claim.grounding.unresolved+plan.harness.legality.unresolved+
        [item for monitor in plan.monitors for item in monitor.grounding.unresolved])
    boundaries=list(dict.fromkeys(unit.scope.excluded+plan.uncertainties+([] if bounded_complete else claim.pending)+semantic_boundaries))
    violated=any(r['outcome']=='violated' for r in results)
    outcome='violated' if violated else 'holds' if bounded_complete else 'unknown'
    return {'direct_check_id':artifact.id,'experiment_check_id':check.id,'scope':artifact.scope.model_dump(mode='json'),
        'raw_log':check.stdout,'parsing_errors':parsing,'prerequisites':prerequisite,'properties':results,
        'adaptations':plan.harness.semantic_changes,
        'blockers':list(dict.fromkeys(blockers+provenance_blockers)),'boundaries':boundaries,
        'reviewed_complete':bounded_complete and not blockers,
        'bounded_complete':bounded_complete,'confirmed':any(r['confirmed'] for r in results),'outcome':outcome,
        'level':'implementation_obligation' if any(r['confirmed'] for r in results) else 'implementation_test',
        'claim_id':claim.id,'claim_version':claim.version}


def persist_assessment(state,artifact,plan,check,record):
    """Upsert the current interpretation for one execution and its checker results."""
    claim=next(c for c in state.claims if c.id==plan.claim_id)
    current=next((r for r in state.monitor_results if r.get('direct_check_id')==artifact.id and r.get('experiment_check_id')==check.id),None)
    if current is None:state.monitor_results.append(record)
    check.checker_results=[CheckerResult(invariant=r['checker_id'],claim_id=claim.id,scope=artifact.scope,
        outcome=r['outcome'],reason=r['reason']) for r in record['properties']]
    for result in record['properties']:
        if not result['comparison_complete']:continue
        assessment=Assessment.STALE if 'Direct-check semantic inputs changed; execution requires rechecking' in record['blockers'] else Assessment.CHALLENGED if result['confirmed'] else Assessment.INCONCLUSIVE
        evidence=next((e for e in state.evidence if e.check_id==check.id and e.direct_check_id==artifact.id and e.checker_id==result['checker_id']),None)
        description=('Finite measured '+result['outcome']+' comparison for direct check '+artifact.id+
            '; current attribution is stored in its monitor result; broader consequences remain outside this evidence')
        if evidence is None:
            state.add_evidence(Evidence(check_id=check.id,model_id=None,direct_check_id=artifact.id,snapshot_id=artifact.snapshot_id,
                claim_id=claim.id,claim_version=claim.version,origin=check.origin,level='framework_test' if state.mode=='mock' else 'implementation_test',
                scope=artifact.scope,checker_id=result['checker_id'],description=description,assessment=assessment))
        else:
            evidence.description=description;evidence.assessment=assessment
        if result['outcome']!='violated':continue
        finding=next((f for f in state.findings if f.direct_check_id==artifact.id and f.check_id==check.id and f.checker_id==result['checker_id']),None)
        if finding is None:
            finding=Finding(claim_id=claim.id,claim_version=claim.version,model_id=None,direct_check_id=artifact.id,check_id=check.id,
                checker_id=result['checker_id'],origin=check.origin,description='Measured direct-check comparison failed; normative attribution is conditional on recorded blockers',trace_path=check.stdout)
            state.findings.append(finding)
        finding.stage=Investigation.REPRODUCED if result['confirmed'] else Investigation.INCONCLUSIVE
        finding.level='implementation_obligation' if result['confirmed'] else 'implementation_candidate'
        record.setdefault('finding_ids',{})[result['checker_id']]=finding.id
    if record.get('finding_ids'):
        primary=next((r['checker_id'] for r in record['properties'] if r['confirmed']),next(iter(record['finding_ids'])))
        record['finding_id']=record['finding_ids'][primary]
    if current is not None:current.clear();current.update(record)
    return record


def assess(state,unit,artifact,plan,check,events):
    return persist_assessment(state,artifact,plan,check,compute_assessment(state,unit,artifact,plan,check,events))


def refresh_assessments(state,artifact_ids,stale_only=False):
    from consensus_assurance.adapters.runners.experiment import extract_events
    units={u.id:u for u in state.units}
    for artifact in state.direct_checks:
        if artifact.id not in artifact_ids or artifact.unit_id not in units:continue
        plan=load_plan(artifact.plan_path)
        for check in state.checks:
            if check.direct_check_id!=artifact.id:continue
            if stale_only and any(r.get('experiment_check_id')==check.id and
                    'Direct-check semantic inputs changed; execution requires rechecking' in r.get('blockers',[]) for r in state.monitor_results):continue
            assess(state,units[artifact.unit_id],artifact,plan,check,extract_events(check))
