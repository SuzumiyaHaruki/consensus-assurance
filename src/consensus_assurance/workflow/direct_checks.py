"""Question routing and bounded implementation checks using existing execution evidence."""
import json
from pathlib import Path
from consensus_assurance.core.proposals import DirectCheckReply, DirectCheckPlan, QuestionReply
from consensus_assurance.core.types import DirectCheckArtifact, CheckRun, CheckerResult, Evidence, Finding, Origin, Assessment, Investigation, ExecutionStatus, uid
from consensus_assurance.core.events import match_prerequisites, event_requirements
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events
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


def route(unit):
    q=unit.audit_question
    if q is None or q.disposition is None:return 'build'  # Offline/regression compatibility only.
    validate_question(q)
    if q.disposition=='explained_by_existing_mechanism':return 'question_closed'
    if q.disposition in {'needs_specific_evidence','concrete_suspicion'}:return 'question'
    return {'local_model':'build','source_review':'question','direct_test':'direct_check','controlled_schedule':'direct_check'}[q.preferred_check]


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
        # History predicates need a complete observed history contract. Initially
        # keep this route to scalar event assertions; unsupported paths are gaps.
        if p is None or p.kind!='event_assertion':
            errors.append('Direct monitor '+monitor.id+' requires the supported shared event assertion')
            continue
        if not p.identity_fields:
            errors.append('Direct monitor '+monitor.id+' needs shared operation/participant/context identity')
        if not monitor.binding_ids or not set(monitor.binding_ids)<=set(plan.binding_ids):errors.append('Monitor '+monitor.id+' needs selected source bindings')
        if p.trigger.reference:errors.append('Direct trigger '+p.checker_id+' must select an actual event field')
        try:event_requirements(plan.harness.prerequisites,p.assertion.reference)
        except ValueError as exc:errors.append(p.checker_id+': '+str(exc))
        if p.assertion.field in p.identity_fields:
            errors.append(p.checker_id+': the compared value cannot also establish independent operation identity')
        if p.trigger.field==p.assertion.field or any(c.field==p.assertion.field for c in monitor.applicability_conditions):
            errors.append(p.checker_id+': trigger/applicability cannot filter on the result field being checked')
    if errors:raise ValueError('; '.join(dict.fromkeys(errors)))


def validate_revision(state,unit,revision):
    from .mutations import validate_changes
    from .feedback import apply_feedback
    validate_changes(state,revision,unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id])
    trial=state.model_copy(deep=True)
    apply_feedback(trial,next(u for u in trial.units if u.id==unit.id),None,revision)


def validate_reply(state,unit,reply,implementation,previous=None):
    if reply.plan:
        if reply.requests or reply.fallback!='none':raise ValueError('Return a plan or a gap/fallback, not competing routes')
        validate_plan(state,unit,reply.plan,implementation)
        if previous:
            left=previous.model_dump();right=reply.plan.model_dump()
            left.pop('harness');right.pop('harness')
            if left!=right:raise ValueError('Technical/F4 direct repair must preserve the selected claim and oracle; use F2/F3 for semantics')
    elif not reply.gap.strip():raise ValueError('Missing direct plan requires a concrete gap')


def save_plan(engine,unit,plan,operation_id):
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
        scope=unit.scope,operation_id=operation_id)
    state.direct_checks.append(artifact)
    return artifact


def execute(engine,artifact):
    if not engine.config.allow_experiments or engine.implementation is None:raise Blocked('Target execution disabled or no execution backend configured')
    plan=load_plan(artifact.plan_path)
    def perform():
        workspace=engine.workspace()
        before=engine.state.snapshot.files
        destination=workspace/engine.implementation.harness_filename
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise Blocked('Generated harness would overwrite target code')
        destination.write_text(plan.harness.source)
        check=run_experiment(engine.runner,engine.implementation.experiment_command(),workspace,engine.state.snapshot.id,
            engine.budget.timeout(),engine.config.execution_isolation,'direct_check',adapter=engine.implementation)
        after=capture(workspace,excluded_dirs={".execution"}).files
        changed=[p for p,value in before.items() if after.get(p)!=value]
        check.direct_check_id=artifact.id
        check.origin=Origin.MOCK if engine.state.mode=='mock' else Origin.EXECUTED
        check.parameters['changed_target_files']=changed
        check.tool_version=engine.state.tools.get('implementation','unknown')
        check.artifacts.append(str(destination))
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
    if not original:blockers.append('Nonoriginal execution cannot confirm implementation')
    if prerequisite['status']!='matched':blockers.append('Correlated prerequisites not established: '+prerequisite['reason'])
    if check.parameters.get('changed_target_files'):blockers.append('Experiment changed target implementation files')
    parsing=[e.get('_ca_observation') for e in events if e.get('event')=='invalid_observation']
    if parsing:blockers.append('Event output contains incomplete or invalid CA_EVENT records')
    if not correspondence and not issues:
        blockers.extend(claim.grounding.conflicts+plan.harness.legality.conflicts+
            [item for monitor in plan.monitors for item in monitor.grounding.conflicts])
    for result in results:
        local=[]
        if result['missing_indices']:local.append('Required observed fields, event identity, or prerequisite association are missing')
        if result['outcome']=='unknown' and not result['missing_indices']:local.append('No applicable result event was reached')
        result['limitations']=local
        result['comparison_complete']=result['outcome'] in {'holds','violated'} and not local
        result['confirmed']=result['outcome']=='violated' and result['comparison_complete'] and not blockers
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
        'blockers':list(dict.fromkeys(blockers)),'boundaries':boundaries,
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
        assessment=Assessment.CHALLENGED if result['confirmed'] else Assessment.INCONCLUSIVE
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


def proceed(engine,unit,phase):
    if engine.implementation is None:raise Blocked('Direct execution unavailable: no execution backend configured')
    state=engine.state
    artifact=next((a for a in state.direct_checks if a.id==state.active_direct_check_id),None)
    if phase!='direct_check' and (artifact is None or artifact.unit_id!=unit.id):raise Blocked('Selected direct artifact is unavailable for this unit')
    plan=load_plan(artifact.plan_path) if artifact else None
    if phase=='direct_check':
        previous=plan if state.pending_feedback else None
        reply,call=engine.ask('direct_check',DirectCheckReply,{**engine.context(unit),'previous_plan':previous.model_dump(mode='json') if previous else None,
            'execution_gap':state.pending_feedback},lambda p:validate_reply(state,unit,p,engine.implementation,previous))
        if reply.plan is None:
            if reply.requests:
                if reply.reading_purpose=='dependency':
                    engine.targeted_read(unit,reply.gap,requests=reply.requests)
                    state.active_direct_check_id=None;engine.advance('select')
                else:
                    engine.read(reply.requests,purpose='depth',plan_id='direct-read-'+call.id,related_ids=[unit.id],reason=reply.gap)
                    engine.advance('direct_check')
                return
            state.gaps.append(reply.gap)
            if reply.fallback in {'local_model','source_review'}:
                state.question_continuations.setdefault(unit.id,{})['fallback']={'kind':reply.fallback,'check_id':call.id,'reason':reply.gap}
                engine.advance('build' if reply.fallback=='local_model' else 'question');return
            engine.finish_unit(unit,'blocked');return
        prior=artifact;cause=state.pending_feedback
        artifact=save_plan(engine,unit,reply.plan,call.id)
        if prior and cause and cause['kind']=='F4':
            from .transactions import commit_graph
            from consensus_assurance.core.types import Revision
            def record_repair(proxy):
                proxy.budget.take('revisions')
                proxy.state.revisions.append(Revision(kind='F4',rationale='Repair direct execution prerequisites; obligation, scope and oracle preserved',
                    evidence_ids=[cause['check_id']],target_ids=[prior.id],relation_ids=[],
                    before={'direct_check_id':prior.id,'plan_path':prior.plan_path},
                    after={'direct_check_id':artifact.id,'plan_path':artifact.plan_path},return_step='experiment'))
            commit_graph(engine,'direct-F4-'+call.id,{'before':prior.id,'after':artifact.id,'check_id':cause['check_id']},record_repair)
        state.active_direct_check_id=artifact.id;state.pending_feedback=None
        engine.advance('direct_execute');return
    if phase=='direct_execute':
        check=execute(engine,artifact)
        record=assess(state,unit,artifact,plan,check,extract_events(check))
        write_json(engine.root/'direct-checks'/artifact.operation_id/(check.id+'-assessment.json'),record)
        from .inquiry import enabled,enqueue
        if enabled(engine) and check.status==ExecutionStatus.COMPLETED:
            enqueue(state,'review','Review the whole direct check against its obligation, actual calls and observations',
                'direct_check:'+artifact.id,target_ids=[artifact.id],unit_id=unit.id)
        engine.advance('direct_assess');return
    check=next(c for c in reversed(state.checks) if c.direct_check_id==artifact.id)
    record=assess(state,unit,artifact,plan,check,extract_events(check))
    write_json(engine.root/'direct-checks'/artifact.operation_id/(check.id+'-assessment.json'),record)
    if record['confirmed']:
        state.active_finding_id=record['finding_id'];engine.advance('consequence_plan');return
    if record['bounded_complete']:
        engine.finish_unit(unit,'checked' if not record['blockers'] else 'blocked');return
    if check.status==ExecutionStatus.ERROR or check.status==ExecutionStatus.COMPLETED and check.exit_code==0 and record['prerequisites']['status']=='not_reached':
        engine.budget.take('technical_repairs' if check.status!=ExecutionStatus.COMPLETED else 'replays')
        state.pending_feedback={'kind':'technical' if check.status!=ExecutionStatus.COMPLETED else 'F4','check_id':check.id,'assessment':record,'failure':engine.error_context(check)}
        engine.advance('direct_check');return
    engine.finish_unit(unit,'blocked')


def continue_question(engine,unit):
    state=engine.state;q=unit.audit_question
    key=unit.id+'@'+str(unit.version)
    session=state.question_continuations.setdefault(key,{'requests':[r.model_dump(mode='json') for r in q.requests],'stage':'read'})
    if session['stage']=='read':
        if session['requests']:
            read_id=session.setdefault('read_plan_id',uid())

            receipt=engine.read(session['requests'],purpose='depth',plan_id=read_id,related_ids=[unit.id],reason=q.question)
            if receipt['status']!='complete':raise Blocked('Selected question dependency read remains incomplete')
        session=state.question_continuations[key]
        session['stage']='continue'
    def validate(reply):
        if reply.revision:
            if reply.patch or reply.requests:raise ValueError('F2 interpretation changes must be a separate complete revision')
            validate_revision(state,unit,reply.revision)
            return
        if reply.patch and (reply.requests or reply.question.requests):raise ValueError('Acquire required source before applying a scope patch')
        validate_question(reply.question)
        old=q.model_dump();new=reply.question.model_dump()
        from .audit_spec import IDENTITY, load, validate_question as validate_spec_question
        if any(new[key]!=old[key] for key in IDENTITY):
            raise ValueError('Question structural meaning changed; use attributed F2 or scope reconnect')
        if not set(q.counterevidence)<=set(reply.question.counterevidence) or not set(q.unknowns)<=set(reply.question.unknowns):
            raise ValueError('Retain unresolved counterevidence; resolve individual issues through semantic review')
        spec=load(state)
        if spec:validate_spec_question(spec,reply.question)
        if reply.patch:
            if len(reply.patch.units)!=1 or reply.patch.units[0].audit_question!=reply.question:raise ValueError('Scope continuation must carry the same complete question on its reconnected unit')
            from .scope_updates import from_patch,validate_scope_update
            validate_scope_update(state,from_patch(state,unit,reply.patch))
    reply,check=engine.ask('question',QuestionReply,{**engine.context(unit),'selected_unit':unit.model_dump(mode='json')},validate)
    if reply.revision:
        engine.budget.take('revisions');engine.commit_feedback(unit,None,reply.revision)
        if state.revisions[-1].status!='applied':engine.finish_unit(unit,'blocked')
        return
    if reply.patch:
        from .scope_updates import from_patch,validate_scope_update,accept,ScopeAssessment
        update=from_patch(state,unit,reply.patch)
        fields=validate_scope_update(state,update)
        if fields:
            update.assessment,_=engine.ask('scope_review',ScopeAssessment,{'scope_update':update.model_dump(mode='json'),'required_fields':fields,**engine.context(unit)})
        validate_scope_update(state,update)
        accept(engine,update)
        # The new unit is selected through its ordinary scope continuation.
        engine.advance('select');return
    from .transactions import commit_graph
    def commit(proxy):
        current=next(u for u in proxy.state.units if u.id==unit.id)
        proxy.state.graph_history.append({'kind':'units','id':current.id,'version':current.version,'record':current.model_dump(mode='json'),'reason':reply.explanation})
        current.audit_question=reply.question
        if reply.requests:current.audit_question.requests=reply.requests
        current.version+=1;proxy.state.graph_version+=1
        proxy.state.question_continuations[key].update(stage='completed',check_id=check.id,explanation=reply.explanation)
        next_phase=route(current)
        repeated=bool(current.audit_question.requests) and all(any(r.file==old.file and r.start_line==old.start_line and r.end_line==old.end_line for old in q.requests) for r in current.audit_question.requests)
        if next_phase=='question' and (not current.audit_question.requests or repeated):
            current.status='blocked';proxy.state.gaps.append(reply.explanation);proxy.state.active_unit_id=None;proxy.state.next_action='select'
        else:proxy.state.next_action=next_phase
    commit_graph(engine,'question-'+check.id,reply.model_dump(mode='json'),commit)
