"""Question routing and bounded implementation checks using existing execution evidence."""
import json
import os
from pathlib import Path
from consensus_assurance.core.proposals import DirectCheckReply, DirectCheckPlan, QuestionReply
from consensus_assurance.core.types import DirectCheckArtifact, CheckRun, Evidence, Finding, Origin, Assessment, Investigation, ExecutionStatus, uid
from consensus_assurance.core.events import compare, match_prerequisites
from consensus_assurance.adapters.storage.files import write_json, digest
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events
from .errors import Blocked
from .graph import validate_grounding
from .observations import monitor_events
from .instrumentation import observation_change_limitations
from .reviews import readiness


def validate_question(question):
    if question is None or question.disposition is None:
        raise ValueError('New autonomous units need a typed question disposition')
    if question.disposition=='ready_for_check' and question.preferred_check is None:
        raise ValueError('Ready question needs preferred_check')
    if question.disposition=='needs_specific_evidence' and not question.requests and not any(p.unknowns for p in question.points):
        raise ValueError('Evidence question needs exact requests or a named discriminator in point unknowns')
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
    if plan.claim_id not in unit.obligation_ids:raise ValueError('Direct check must select one unit obligation')
    if not set(plan.binding_ids)<=set(unit.binding_ids):raise ValueError('Direct check uses nonselected bindings')
    for binding in state.bindings:
        if binding.id in plan.binding_ids and (binding.snapshot_id!=state.snapshot.id or state.snapshot.files.get(binding.file)!=binding.content_digest):
            raise ValueError('Direct binding does not describe the selected source snapshot')
    if plan.harness.kind!=implementation.harness_kind:raise ValueError('Unsupported direct harness kind')
    if not plan.harness.prerequisites:raise ValueError('Direct check needs observable correlated prerequisites')
    if not plan.harness.legal_conditions:raise ValueError('Direct check needs observable legality conditions')
    materials={m.id:m for m in state.materials}
    for basis in [plan.harness.legality]+[m.grounding for m in plan.monitors]:
        validate_grounding(basis,materials,set(plan.binding_ids))
    props={p.checker_id:p for p in plan.observable_properties}
    if len(props)!=len(plan.observable_properties) or len({m.id for m in plan.monitors})!=len(plan.monitors):raise ValueError('Duplicate direct property or monitor')
    if set(props)!={m.checker_id for m in plan.monitors}:raise ValueError('Direct property/monitor mismatch')
    for monitor in plan.monitors:
        p=props.get(monitor.checker_id)
        # History predicates need a complete observed history contract. Initially
        # keep this route to scalar event assertions; unsupported paths are gaps.
        if p is None or p.kind!='event_assertion' or p!=monitor.property or monitor.conditions!=[p.trigger] or monitor.assertion!=p.assertion:
            raise ValueError('Direct monitor requires the supported shared event assertion')
        if not monitor.identity_fields or monitor.identity_fields!=p.identity_fields:
            raise ValueError('Direct monitor needs shared operation/participant/context identity')
        if not monitor.binding_ids or not set(monitor.binding_ids)<=set(plan.binding_ids):raise ValueError('Monitor needs selected source bindings')
        if not monitor.applicability_conditions:raise ValueError('Monitor needs observed applicability conditions')
        if p.trigger.reference or p.assertion.reference:raise ValueError('Direct assertions use actual event fields; aliases belong to prerequisites')
        witness=[r for r in plan.harness.prerequisites[1:] if r.event==monitor.event]
        aliases={r.alias for r in plan.harness.prerequisites}
        if not any(all(any(c.field==key and c.op=='eq' and c.reference and c.reference.partition('.')[0] in aliases and c.reference.partition('.')[2]==key for c in r.conditions) for key in monitor.identity_fields) for r in witness):
            raise ValueError('Monitor witness must correlate each identity to prerequisite events')


def validate_revision(state,unit,revision):
    from .mutations import validate_changes
    from .feedback import apply_feedback
    validate_changes(state,revision,unit.goal_ids+unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id])
    trial=state.model_copy(deep=True)
    apply_feedback(trial,next(u for u in trial.units if u.id==unit.id),None,revision)


def validate_reply(state,unit,reply,implementation,previous=None):
    if reply.plan:
        if reply.requests or reply.fallback!='none':raise ValueError('Return a plan or a gap/fallback, not competing routes')
        validate_plan(state,unit,reply.plan,implementation)
        if previous:
            left=previous.model_dump();right=reply.plan.model_dump()
            left.pop('harness');right.pop('harness')
            if left!=right:raise ValueError('Technical/F4 direct repair must preserve scope and oracle; use F2/F3 for semantics')
    elif not reply.gap.strip():raise ValueError('Missing direct plan requires a concrete gap')


def save_plan(engine,unit,plan,operation_id):
    state=engine.state
    validate_plan(state,unit,plan,engine.implementation)
    folder=engine.root/'direct-checks'/operation_id
    if (folder/'commit.json').exists():
        artifact=DirectCheckArtifact.model_validate_json((folder/'commit.json').read_text())
        current={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units}
        if artifact.snapshot_id!=state.snapshot.id or artifact.unit_id!=unit.id or any(current.get(k)!=v for k,v in artifact.graph_versions.items()):raise ValueError('Direct commit semantic inputs changed')
        if json.loads(Path(artifact.plan_path).read_text())!=plan.model_dump(mode='json'):raise ValueError('Direct commit action inputs changed')
        if any(not Path(p).is_file() or digest(Path(p).read_bytes())!=d for p,d in artifact.artifact_digests.items()):raise ValueError('Direct artifact changed')
    else:
        temporary=folder.with_name('.pending-'+operation_id)
        if temporary.exists():temporary.rename(temporary.with_name(temporary.name+'-incomplete-'+uid()))
        temporary.mkdir(parents=True,exist_ok=False)
        write_json(temporary/'plan.json',plan)
        (temporary/engine.implementation.harness_filename).write_text(plan.harness.source)
        from .inputs import semantic_ids
        ids=semantic_ids(state,unit)
        artifact=DirectCheckArtifact(plan_path=str(folder/'plan.json'),harness_path=str(folder/engine.implementation.harness_filename),
            artifact_digests={str(folder/p.name):digest(p.read_bytes()) for p in [temporary/'plan.json',temporary/engine.implementation.harness_filename]},
            snapshot_id=state.snapshot.id,unit_id=unit.id,claim_id=plan.claim_id,binding_ids=plan.binding_ids,
            graph_versions={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units if o.id in ids},
            origin=Origin.MOCK if state.mode=='mock' else Origin.PRESET if state.analysis_mode=='regression' else Origin.AGENT,
            scope=plan.scope,operation_id=operation_id)
        write_json(temporary/'commit.json',artifact)
        os.rename(temporary,folder)
    if not any(a.id==artifact.id for a in state.direct_checks):state.direct_checks.append(artifact)
    return artifact


def execute(engine,artifact,plan):
    if not engine.config.allow_experiments:raise Blocked('Target execution disabled')
    def perform():
        if any(not Path(p).is_file() or digest(Path(p).read_bytes())!=v for p,v in artifact.artifact_digests.items()):raise Blocked('Saved direct artifact changed')
        workspace=engine.workspace()
        before=capture(workspace).files
        if before!=engine.state.snapshot.files:raise Blocked("Execution source differs from the selected snapshot")
        destination=workspace/engine.implementation.harness_filename
        if destination.exists():raise Blocked('Generated harness would overwrite target code')
        destination.write_text(plan.harness.source)
        check=run_experiment(engine.runner,engine.implementation.experiment_command(),workspace,engine.state.snapshot.id,
            engine.budget.timeout(),engine.config.execution_isolation,'direct_check',adapter=engine.implementation)
        after=capture(workspace,excluded_dirs={".execution"}).files
        changed=[p for p,value in before.items() if after.get(p)!=value]
        check.direct_check_id=artifact.id;check.input_versions=artifact.artifact_digests
        check.origin=Origin.MOCK if engine.state.mode=='mock' else Origin.EXECUTED
        check.parameters['changed_target_files']=changed
        check.tool_version=engine.state.tools.get('implementation','unknown')
        check.artifacts.append(str(destination))
        return check
    check=CheckRun.model_validate(engine.action('direct_execute','experiments',perform,{'direct_check_id':artifact.id,'inputs':artifact.artifact_digests}))
    engine.record(check)
    return check


def assess(state,unit,artifact,plan,check,events):
    prerequisite=match_prerequisites(events,plan.harness.prerequisites)
    results=[monitor_events(events,m) for m in plan.monitors]
    limitations=list(plan.uncertainties)
    if DirectCheckPlan.model_validate_json(Path(artifact.plan_path).read_text())!=plan:limitations.append('Plan differs from saved executable input')
    validate_plan(state,unit,plan,type('Adapter',(),{'harness_kind':plan.harness.kind})())
    claim=next(c for c in state.claims if c.id==plan.claim_id)
    from .task_view import semantic_view
    ids=set(artifact.graph_versions)|{a.id for a in state.direct_checks if a.unit_id in {unit.id,unit.previous_id}}
    semantics,_=semantic_view(state,ids)
    if readiness(state,unit)['status']!='reviewed':limitations.append('Selected question semantics remain exploratory')
    correspondence=[r for r in state.semantic_reviews if r.target_versions.get(artifact.id)==artifact.version and any(i.target_id==artifact.id and i.aspect=='checker_correspondence' and i.status=='no_issue_found' and not i.limitations for i in r.items)]
    if not correspondence:limitations.append('Direct oracle correspondence is unreviewed')
    if semantics['open_issues'] or any(i['status']!='no_issue_found' or i['limitations'] for i in semantics['judgments']):limitations.append('Unresolved semantic counterevidence')
    current={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units+state.direct_checks}
    from .reviews import valid_supersession
    for task in state.inquiry_tasks:
        if task.kind=='review' and task.status in {'pending','running','blocked'} and not task.superseded_by and not any(valid_supersession(state,r,task) for r in state.semantic_reviews) and any(id in ids and task.target_versions.get(id)==current.get(id) for id in task.target_ids):
            limitations.append('Relevant semantic review is unfinished: '+task.id)
    if any(current.get(k)!=v for k,v in artifact.graph_versions.items()):limitations.append('Direct semantic inputs changed')
    if check.status!=ExecutionStatus.COMPLETED or check.exit_code!=0:limitations.append('Execution failed; not property evidence')
    if check.snapshot_id!=artifact.snapshot_id or check.direct_check_id!=artifact.id or check.input_versions!=artifact.artifact_digests:limitations.append('Direct input association mismatch')
    if any(not Path(p).is_file() or digest(Path(p).read_bytes())!=v for p,v in artifact.artifact_digests.items()):limitations.append('Saved direct artifact changed')
    if state.mode=='mock' or artifact.origin in {Origin.MOCK,Origin.SYNTHETIC,Origin.MUTATION,Origin.IMPORTED} or check.origin!=Origin.EXECUTED:limitations.append('Nonoriginal execution cannot confirm implementation')
    if prerequisite['status']!='matched':limitations.append('Correlated prerequisites not established')
    if check.parameters.get('changed_target_files'):limitations.append('Experiment changed target implementation files')
    limitations.extend(observation_change_limitations(plan.harness,artifact.binding_ids))
    limitations.extend(claim.pending)
    for basis in [claim.grounding,plan.harness.legality]+[m.grounding for m in plan.monitors]:limitations.extend(basis.unresolved+basis.conflicts)
    for condition in plan.harness.legal_conditions:
        if not events or not all(compare(e,condition) is True for e in events):limitations.append('Observable execution legality not established')
    for monitor,result in zip(plan.monitors,results):
        local=[]
        matched=[i for i,e in enumerate(events) if e.get('event')==monitor.event and all(compare(e,c) is True for c in monitor.conditions)]
        if result['missing_indices']:local.append('Required observed fields missing')
        if not matched or any(not all(compare(events[i],c) is True for c in monitor.applicability_conditions) for i in matched):local.append('Observable applicability not established')
        if not set(matched)<=set(prerequisite['matched_indices']):local.append('Observed checks are outside the correlated prerequisite execution')
        result['limitations']=local
    violated=any(r['outcome']=='violated' for r in results)
    clean=not limitations and all(not r['limitations'] and r['outcome']!='unknown' for r in results)
    confirmed=clean and violated
    record={'direct_check_id':artifact.id,'experiment_check_id':check.id,'prerequisites':prerequisite,'properties':results,
        'limitations':limitations,'confirmed':confirmed,'outcome':'violated' if confirmed else 'holds' if clean else 'unknown',
        'level':'implementation_obligation' if confirmed else 'implementation_test','claim_id':claim.id,'claim_version':claim.version}
    # Keep exploratory passing traces, with their limitations, separate from proof.
    if check.status==ExecutionStatus.COMPLETED and check.exit_code==0 and prerequisite['status']=='matched' and all(r['outcome']!='unknown' and not r['limitations'] for r in results):
        if not any(e.check_id==check.id and e.direct_check_id==artifact.id and e.assessment==(Assessment.CHALLENGED if confirmed else Assessment.INCONCLUSIVE) for e in state.evidence):
            state.add_evidence(Evidence(check_id=check.id,model_id=None,direct_check_id=artifact.id,snapshot_id=artifact.snapshot_id,
                claim_id=claim.id,claim_version=claim.version,origin=check.origin,level='framework_test' if state.mode=='mock' else 'implementation_test',
                scope=plan.scope,description='Finite actual direct check; '+json.dumps(record),assessment=Assessment.CHALLENGED if confirmed else Assessment.INCONCLUSIVE))
    if violated:
        finding=next((f for f in state.findings if f.direct_check_id==artifact.id and f.check_id==check.id),None)
        if finding is None:
            finding=Finding(claim_id=claim.id,claim_version=claim.version,model_id=None,direct_check_id=artifact.id,check_id=check.id,
                origin=check.origin,description='Observed direct-check violation candidate; interpretation is conditional on recorded limitations',trace_path=check.stdout)
            state.findings.append(finding)
        finding.stage=Investigation.REPRODUCED if confirmed else Investigation.INCONCLUSIVE
        finding.level='implementation_obligation' if confirmed else 'implementation_candidate'
        record['finding_id']=finding.id
    state.monitor_results.append(record)
    return record


def proceed(engine,unit,phase):
    state=engine.state
    artifact=next((a for a in state.direct_checks if a.id==state.active_direct_check_id),None)
    if phase!='direct_check' and (artifact is None or artifact.unit_id!=unit.id):raise Blocked('Selected direct artifact is unavailable for this unit')
    plan=DirectCheckPlan.model_validate_json(Path(artifact.plan_path).read_text()) if artifact else None
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
        execute(engine,artifact,plan);engine.advance('direct_assess');return
    check=next(c for c in reversed(state.checks) if c.direct_check_id==artifact.id)
    record=assess(state,unit,artifact,plan,check,extract_events(check))
    write_json(engine.root/'direct-checks'/artifact.operation_id/(check.id+'-assessment.json'),record)
    if record.get('finding_id') and not record['confirmed'] and not any(t.trigger.startswith('direct_witness:') and check.id in t.trigger and t.unit_id==unit.id for t in state.inquiry_tasks):
        from .inquiry import review_unit,enqueue
        review_unit(engine,unit,'direct_witness:'+check.id)
        enqueue(state,'review','Interpret actual direct oracle witness','direct_witness:oracle:'+check.id,target_ids=[artifact.id],unit_id=unit.id)
        engine.checkpoint('direct_witness_review_pending');return
    if record['confirmed']:
        state.active_finding_id=record['finding_id'];engine.advance('consequence_plan');return
    if check.status!=ExecutionStatus.COMPLETED or check.exit_code!=0 or record['prerequisites']['status']!='matched':
        engine.budget.take('technical_repairs' if check.status!=ExecutionStatus.COMPLETED else 'replays')
        state.pending_feedback={'kind':'technical' if check.status!=ExecutionStatus.COMPLETED else 'F4','check_id':check.id,'assessment':record,'failure':engine.error_context(check)}
        engine.advance('direct_check');return
    engine.finish_unit(unit,'blocked')  # Finite test never discharges the entire obligation.


def continue_question(engine,unit):
    state=engine.state;q=unit.audit_question
    key=unit.id+'@'+str(unit.version)
    session=state.question_continuations.setdefault(key,{'requests':[r.model_dump(mode='json') for r in q.requests],'stage':'read'})
    if session['stage']=='read':
        if session['requests']:
            read_id=session.setdefault('read_plan_id',uid())
            engine.checkpoint('question_read_planned')
            receipt=engine.read(session['requests'],purpose='depth',plan_id=read_id,related_ids=[unit.id],reason=q.question)
            if receipt['status']!='complete':raise Blocked('Selected question dependency read remains incomplete')
        session=state.question_continuations[key]
        session['stage']='continue';engine.checkpoint('question_dependency_read')
    def validate(reply):
        if reply.revision:
            if reply.patch or reply.requests:raise ValueError('F2 interpretation changes must be a separate complete revision')
            validate_revision(state,unit,reply.revision)
            return
        if reply.patch and (reply.requests or reply.question.requests):raise ValueError('Acquire required source before applying a scope patch')
        validate_question(reply.question)
        old=q.model_dump();new=reply.question.model_dump()
        for field_name in ('question','importance'):
            if new[field_name]!=old[field_name]:raise ValueError('Question continuation preserves meaning; reinterpretation requires F2')
        for field_name in ('source_ids','participants','objects','contexts','event_paths'):
            if not set(old[field_name])<=set(new[field_name]):raise ValueError('Question continuation cannot erase existing scope or counterevidence')
        for point in q.points:
            if point not in reply.question.points:raise ValueError('Retain old coverage opinions; resolve individual issues through semantic review')
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
