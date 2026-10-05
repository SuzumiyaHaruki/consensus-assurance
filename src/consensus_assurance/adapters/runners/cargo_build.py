"""Run-local Cargo inputs and private copies of an isolated, unexecuted build seed."""
import json
import os
import shutil
import time
from pathlib import Path
from .experiment import clean_environment, sandbox_command, run_experiment
from .process import output
from ..storage.files import digest, write_json
from ..storage.snapshot import capture
from ...core.types import CheckRun, ExecutionStatus, uid, now

VIEW = Path('/tmp/consensus-cargo')


def diagnostics(text):
    """Cargo messages describe compilation; libtest output separately witnesses execution."""
    import re
    messages=[]
    for line in text.splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):messages.append(value)
        except ValueError:pass
    artifacts=[{k:m.get(k) for k in ('package_id','manifest_path','target','profile','features','fresh','executable','filenames')}
        for m in messages if m.get('reason')=='compiler-artifact']
    finishes=[m.get('success') for m in messages if m.get('reason')=='build-finished']
    started=bool(re.search(r'(?m)^running [1-9][0-9]* tests?$',text))
    result=re.search(r'(?m)^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;',text)
    return {'compiler_artifacts':artifacts, 'build_finished':finishes[-1] if finishes else None,
        'build_activity':bool(artifacts or re.search(r'(?m)^\s*Compiling ',text)),
        'test_started':started, 'test_passed':bool(result and int(result[1])>0),
        'test_summary_recorded':bool(result)}


def tool_inputs(adapter,deadline=None):
    import subprocess
    commands=[[str(adapter.cargo),'--version','--verbose'],adapter.version_command()]
    commands += [[shutil.which(name),'--version'] for name in ('cc','c++','ar') if shutil.which(name)]
    result=[]
    for cmd in commands:
        remaining=10 if deadline is None else min(10,deadline-time.monotonic())
        if remaining<=0:raise ValueError('Runtime deadline reached before Cargo tool verification')
        try:version=subprocess.check_output(cmd,text=True,stderr=subprocess.STDOUT,timeout=remaining).strip()
        except (subprocess.SubprocessError,OSError) as exc:raise ValueError('Cargo tool verification failed: '+str(cmd)) from exc
        result.append({'command':cmd,'version':version})
    return result


def verify(adapter,root,snapshot_id,deadline=None):
    """Also run before operation-result reuse; dependencies are not just Python config."""
    records=list((root/'build-inputs/targets').glob('**/basis.json'))
    if not records:return
    source_files=capture(root/'source').files
    tools=tool_inputs(adapter,deadline)
    for path in records:
        basis=json.loads(path.read_text())
        lock=root/basis['lock']['record']
        if (basis['snapshot_id']!=snapshot_id or basis['source_files']!=source_files or basis['tools']!=tools
                or basis['policy']!=policy(adapter) or lock.is_symlink() or not lock.is_file()
                or digest(lock.read_bytes())!=basis['lock']['digest']):
            raise ValueError('Cargo build inputs or tools changed; start a new run; cached results cannot be reused')


def policy(adapter):
    return {'profile':'test','feature_selection':'No extra feature flags; original dependency and dev-dependency unification applies',
        'offline':True,'locked':True,'jobs':2,'cargo':str(adapter.cargo),'rustc':str(adapter.cargo.parent/'rustc'),
        'target_selection':'rustc host unless overridden by captured Cargo configuration; compiler artifact paths retained',
        'rustdoc':str(adapter.cargo.parent/'rustdoc'),'sandbox_source':str(VIEW),
        'inherited_environment':{k:os.environ[k] for k in ('PATH','LANG','LC_ALL','JAVA_HOME') if k in os.environ},
        'environment':'Controller-owned HOME, TMPDIR and Cargo settings; no host Cargo configuration or flags'}


class PreparationFailed(Exception):
    def __init__(self,check):self.check=check


def build_inputs(adapter,root,state,read):
    """Read bounded preparation metadata, never validate tools or materialize a seed."""
    selected=[(adapter.package,adapter.harness_filename)]
    for artifact in state.direct_checks:
        harness=read(f'direct-checks/{artifact.operation_id}/plan.json').get('harness',{})
        if harness.get('kind')=='rust_test':
            package=harness.get('execution_package') or adapter.package
            selected.append((package,str(Path(package)/'tests'/Path(artifact.harness_path).name)))
    current=state.current_submission
    if current.get('harness',{}).get('kind')=='rust_test':
        selected.append((current['harness']['execution_package'],current['harness_filename']))
    paths={p.relative_to(root) for p in (root/'build-inputs/targets').glob('**/basis.json')}
    for package,filename in selected:
        command=adapter.experiment_command(package,filename)
        paths.add(Path('build-inputs/targets')/Path(command[command.index('--manifest-path')+1]).parent/Path(filename).stem/'basis.json')
    result=[]
    for path in sorted(paths):
        basis=read(str(path));manifest=str(path.parent.parent.relative_to('build-inputs/targets')/'Cargo.toml')
        target=path.parent.name;compilations=[];preparations=[]
        basis_digest=digest((root/path).read_bytes()) if basis else None
        for saved in sorted((root/path).parent.glob('*-seed.json')):
            name=str(saved.relative_to(root));receipt=read(name)
            if not basis or receipt.get('basis')!=str(path) or receipt.get('basis_digest')!=basis_digest:continue
            compilations.append({'record':name,'compiled_features':receipt['selected_features']})
            check=read(f'logs/{receipt["check_id"]}/check.json')
            if check:preparations.append((check['started_at'] or '',{'record':f'logs/{check["id"]}/check.json',
                'stage':check['action'],'status':check['status']}))
        cache=root/'.execution/cargo-seeds'/path.parent.relative_to('build-inputs/targets')
        ready=read(str((cache/'ready.json').relative_to(root)))
        available=bool(ready and any(ready==read(c['record']) for c in compilations))
        status='seed_available' if available else 'seed_unavailable' if compilations else 'inputs_fixed' if basis else 'unprepared'
        for check in state.checks:
            params=check.parameters
            same=params.get('build_inputs')==str(path) or (
                params.get('execution_package') is not None and params.get('harness_filename') is not None and
                str(Path(params['execution_package'])/'Cargo.toml')==manifest and Path(params['harness_filename']).stem==target)
            if same and params.get('preparation_failure'):
                preparations.append((check.started_at or '',{'record':f'logs/{check.id}/check.json',
                    'stage':params['preparation_stage'],'status':check.status.value,'failure_record':f'logs/{params["preparation_failure"]}/check.json'}))
        latest=max(preparations,key=lambda p:p[0])[1] if preparations else None
        if latest and 'failure_record' in latest:status='preparation_failed'
        result.append({'record':str(path) if basis else None,'manifest':manifest,'test_target':target,
            'resolved_features':basis.get('resolved_features'),'feature_evidence':basis.get('feature_evidence'),
            'compilations':compilations,'status':status,'latest_preparation':latest})
    return result


def retain_diagnostics(check,text):
    facts=diagnostics(text);artifacts=facts.pop('compiler_artifacts')
    if check.stdout and artifacts:
        path=Path(check.stdout).parent/'cargo-artifacts.json';write_json(path,artifacts)
        facts.update(cargo_artifacts=str(path),fresh_artifacts=sum(a['fresh'] is True for a in artifacts),
            rebuilt_artifacts=sum(a['fresh'] is False for a in artifacts))
    check.parameters.update(facts)
    return facts


def invoke(adapter,runner,command,workspace,snapshot_id,deadline,action):
    env={k:v.replace(str(workspace),str(VIEW)) for k,v in clean_environment(workspace,adapter).items()}
    check=runner.run(sandbox_command(command,workspace,'bwrap',adapter.read_only_roots(),VIEW),workspace,
        action,snapshot_id,max(0,deadline-time.monotonic()),env=env)
    retain_diagnostics(check,output(check))
    write_json(runner.root/'logs'/check.id/'check.json',check)
    if check.status!=ExecutionStatus.COMPLETED or check.exit_code!=0:raise PreparationFailed(check)
    return check


def inputs(adapter,runner,snapshot_id,command,deadline):
    root=runner.root;source=root/'source'
    if not source.is_dir():raise ValueError('Cargo preparation requires the retained source snapshot')
    manifest=command[command.index('--manifest-path')+1];target=command[command.index('--test')+1]
    package=Path(manifest).parent
    folder=root/'build-inputs/targets'/package/target
    record=folder/'basis.json'
    verify(adapter,root,snapshot_id,deadline)
    if record.exists():return record,json.loads(record.read_text())
    work=root/'.execution/cargo-preparation'/uid()/'workspace'
    shutil.copytree(source,work)
    stages=[]
    def run(args,label):
        check=invoke(adapter,runner,[str(adapter.cargo),*args],work,snapshot_id,deadline,label)
        stages.append(check.id);return check
    located=run(['locate-project','--workspace','--message-format','plain','--manifest-path',manifest],'cargo_workspace')
    workspace_manifest=Path(Path(located.stdout).read_text().strip()).relative_to(VIEW)
    lock_path=workspace_manifest.parent/'Cargo.lock'
    saved_lock=root/'build-inputs/workspaces'/lock_path
    lock_origin='source' if (source/lock_path).is_file() else 'prepared'
    if saved_lock.exists():
        (work/lock_path).write_bytes(saved_lock.read_bytes())
    elif not (work/lock_path).exists():
        run(['generate-lockfile','--offline','--manifest-path',manifest],'cargo_lock_prepare')
    metadata=run(['metadata','--locked','--offline','--format-version','1','--manifest-path',manifest],'cargo_metadata')
    resolved=json.loads(Path(metadata.stdout).read_text())
    selected=next(p for p in resolved['packages'] if p['manifest_path']==str(VIEW/manifest))
    node=next(n for n in resolved['resolve']['nodes'] if n['id']==selected['id'])
    if not saved_lock.exists():
        saved_lock.parent.mkdir(parents=True,exist_ok=True);saved_lock.write_bytes((work/lock_path).read_bytes())
    basis={'snapshot_id':snapshot_id,'source_files':capture(source).files,'manifest':manifest,'test_target':target,
        'workspace_manifest':str(workspace_manifest),'package_id':selected['id'],'package_name':selected['name'],
        'lock':{'path':str(lock_path),'record':str(saved_lock.relative_to(root)),
            'origin':lock_origin,'digest':digest(saved_lock.read_bytes())},
        'tools':tool_inputs(adapter,deadline),'policy':policy(adapter),'metadata_check':metadata.id,
        'resolved_features':node['features'],'feature_evidence':'metadata resolution; selected test compilation is recorded separately',
        'preparation_checks':stages,'prepared_at':now()}
    write_json(record,basis)
    return record,basis


def seed(adapter,runner,snapshot_id,command,record,basis,deadline):
    root=runner.root
    destination=root/'.execution/cargo-seeds'/record.parent.relative_to(root/'build-inputs/targets')
    receipt=destination/'ready.json'
    if receipt.is_file():return destination,json.loads(receipt.read_text())
    work=root/'.execution/cargo-preparation'/uid()/'workspace'
    shutil.copytree(root/'source',work)
    (work/basis['lock']['path']).write_bytes((root/basis['lock']['record']).read_bytes())
    filename=Path(basis['manifest']).parent/'tests'/(basis['test_target']+'.rs')
    if (work/filename).exists():raise ValueError('Build seed cannot overwrite an existing source test')
    # A neutral integration target builds the original crate and dev-dependency graph, never a candidate.
    probe='#[test]\nfn assurance_build_ready() { assert!(cfg!(test)); }\n'
    (work/filename).parent.mkdir(parents=True,exist_ok=True);(work/filename).write_text(probe)
    (record.parent/'probe.rs').write_text(probe)
    compile_command=command[:command.index('--')]+['--no-run']
    check=invoke(adapter,runner,compile_command,work,snapshot_id,deadline,'cargo_seed_build')
    if check.parameters['build_finished'] is not True:raise ValueError('Cargo seed has no successful build-finished record')
    if any(not (work/p).is_file() or digest((work/p).read_bytes())!=value for p,value in basis['source_files'].items()):
        raise ValueError('Preparation modified captured source; no seed published')
    if digest((work/basis['lock']['path']).read_bytes())!=basis['lock']['digest']:
        raise ValueError('Preparation changed the fixed dependency lock; no seed published')
    # A submitted file can predate the seed. Let Cargo remove the selected package's
    # outputs so its neutral test binary can never masquerade as the actual harness.
    cleaned=invoke(adapter,runner,[str(adapter.cargo),'clean','--offline','--locked','--manifest-path',basis['manifest'],
        '--package',basis['package_name']],work,snapshot_id,deadline,'cargo_seed_clean_target')
    artifacts=json.loads(Path(check.parameters['cargo_artifacts']).read_text())
    data={'basis':str(record.relative_to(root)),'check_id':check.id,
        'record':str((record.parent/(check.id+'-seed.json')).relative_to(root)),
        'clean_check_id':cleaned.id,
        'compiler_artifacts':str(Path(check.parameters['cargo_artifacts']).relative_to(root)),
        'selected_features':sorted({f for a in artifacts if a['package_id']==basis['package_id'] for f in a['features']}),
        'probe':str((record.parent/'probe.rs').relative_to(root)),
        'basis_digest':digest(record.read_bytes())}
    write_json(root/data['record'],data)
    # Publish only after the isolated build exits; no target test has run in this directory.
    if destination.exists():shutil.rmtree(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    (work/'.execution/cargo-target').rename(destination)
    write_json(receipt,data)
    return destination,data


def execute(adapter,runner,command,workspace,snapshot_id,timeout,mode,action):
    if mode!='bwrap':raise ValueError('Prepared Cargo execution requires bubblewrap; no workspace fallback')
    started=now();clock=time.monotonic();deadline=min(clock+timeout,runner.deadline or float('inf'))
    prior=[CheckRun.model_validate_json(p.read_text()) for p in (runner.root/'logs').glob('*/check.json')]
    prior=[c for c in prior if runner.active_action_id and c.pending_action_id==runner.active_action_id]
    executed=[c for c in prior if c.action==action and c.cwd==str(workspace.resolve()) and c.snapshot_id==snapshot_id]
    if len(executed)>1:raise ValueError('Multiple target receipts in one Cargo action; execution ownership is unresolved')
    if executed:
        expected=runner.root/'build-inputs/targets'/Path(command[command.index('--manifest-path')+1]).parent/command[command.index('--test')+1]/'basis.json'
        if not expected.is_file():raise ValueError('Saved Cargo execution lost its fixed build inputs; cannot reconstruct them for result reuse')
    record=None;basis=None
    try:
        record,basis=inputs(adapter,runner,snapshot_id,command,deadline)
        if executed:
            check=executed[0]
            if check.parameters.get('preparation_failure'):return check
            if check.command!=sandbox_command(command,workspace,mode,adapter.read_only_roots(),VIEW):
                raise ValueError('Saved Cargo execution command differs from the fixed input')
            if not check.ended_at:raise ValueError('Target outcome unknown; same-action replay is prohibited; use an explicit new attempt')
            if 'lock_unchanged' in check.parameters and 'changed_target_files' in check.parameters:
                return check
            # A raw process receipt cannot establish post-execution integrity. Do not
            # repair its workspace and then treat the repaired files as old evidence.
            retain_diagnostics(check,output(check))
            check.parameters.update(execution_backend={'name':adapter.name,'version':adapter.version},
                action_seconds=None,action_started_at=None,changed_target_files=None,build_inputs=str(record.relative_to(runner.root)))
            if check.status==ExecutionStatus.COMPLETED:check.status=ExecutionStatus.ERROR
            check.outcome='unknown';check.reason='Target receipt recovered without integrity postprocessing; no target replay; action total unrecorded'
            return check
        cached,receipt=seed(adapter,runner,snapshot_id,command,record,basis,deadline)
        if receipt['basis_digest']!=digest(record.read_bytes()):raise ValueError('Cargo seed belongs to different build inputs')
        lock=workspace/basis['lock']['path']
        if lock.exists() and lock.read_bytes()!=(runner.root/basis['lock']['record']).read_bytes():
            raise ValueError('Execution lock differs from the saved build inputs')
        lock.write_bytes((runner.root/basis['lock']['record']).read_bytes())
        target=workspace/'.execution/cargo-target'
        # An old copy receipt does not prove that its side effect still exists.
        # Materialize into a new private staging directory, then publish the complete copy.
        staging=target.with_name('cargo-copy-'+uid());staging.mkdir(parents=True)
        copied=runner.run(['cp','-a','--reflink=auto',str(cached)+'/.',str(staging)],workspace,'cargo_seed_copy',snapshot_id,max(0,deadline-time.monotonic()))
        if copied.status!=ExecutionStatus.COMPLETED or copied.exit_code!=0:raise PreparationFailed(copied)
        if target.exists():shutil.rmtree(target)
        staging.rename(target)
        check=run_experiment(runner,command,workspace,snapshot_id,max(0,deadline-time.monotonic()),mode,action,
            adapter,prepared=True,view_path=VIEW)
        check.parameters.update(build_inputs=str(record.relative_to(runner.root)),seed_build=receipt['check_id'],
            seed_record=receipt['record'],
            cache_copy_check=copied.id,cache_reuse='Private seed copy; compiler-artifact fresh fields record actual reuse',
            lock_unchanged=lock.is_file() and digest(lock.read_bytes())==basis['lock']['digest'])
        if not check.parameters['lock_unchanged']:
            check.status=ExecutionStatus.ERROR;check.outcome='unknown';check.reason='Test changed fixed Cargo.lock'
        actual=capture(workspace,excluded_dirs={'.execution'}).files
        check.parameters['changed_target_files']=[p for p,d in basis['source_files'].items() if actual.get(p)!=d]
        check.artifacts += [str(record),str(runner.root/basis['lock']['record']),str(runner.root/receipt['record'])]
    except PreparationFailed as failure:
        original=failure.check
        check=original.model_copy(deep=True,update={'id':uid(),'action':action,'cwd':str(workspace)})
        check.parameters.update(preparation_failure=original.id,preparation_stage=original.action,
            execution_backend={'name':adapter.name,'version':adapter.version})
        if check.status==ExecutionStatus.COMPLETED:check.status=ExecutionStatus.ERROR
        check.outcome='unknown';check.reason=original.action+' did not complete; inspect preparation logs'
        if record:check.parameters['build_inputs']=str(record.relative_to(runner.root))
    check.parameters.update(action_seconds=None if prior else time.monotonic()-clock,action_started_at=None if prior else started)
    if prior:check.reason='; '.join(filter(None,[check.reason,'Interrupted action total unrecorded; original subprocess timings retained']))
    write_json(runner.root/'logs'/check.id/'check.json',check)
    return check
