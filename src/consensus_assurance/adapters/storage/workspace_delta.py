"""Reconstruct future experiment inputs from retained source and generated deltas."""
import json
import shutil
from pathlib import Path
from .snapshot import capture
from .files import write_json,digest


def save_delta(source,workspace,snapshot_id,phase="input"):
    source,workspace=Path(source),Path(workspace)
    base=capture(source).files
    actual={p:d for p,d in capture(workspace,excluded_dirs={".execution"}).files.items() if '.execution' not in Path(p).parts}
    folder=workspace.parent/('workspace-delta' if phase=='input' else 'workspace-outcome');folder.mkdir(exist_ok=True)
    changed={p:d for p,d in actual.items() if base.get(p)!=d}
    for relative in changed:
        out=folder/'files'/relative;out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(workspace/relative,out)
    manifest={'phase':phase,'snapshot_id':snapshot_id,'source_files':base,'changed_files':changed,'removed_files':sorted(set(base)-set(actual)),
        'excluded':['.execution','credential-like and instruction files excluded by the existing snapshot policy'],
        'basis':'Retained run/source plus this delta reproduces captured execution files; caches and external environment are not included'}
    write_json(folder/'manifest.json',manifest)
    return folder/'manifest.json'


def restore(source,manifest,destination):
    source,manifest,destination=Path(source),Path(manifest),Path(destination)
    data=json.loads(manifest.read_text())
    if capture(source).files!=data['source_files']:raise ValueError('Retained source differs from execution delta base')
    for relative in list(data['changed_files'])+data['removed_files']:
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe delta path')
    for relative,expected in data['changed_files'].items():
        path=manifest.parent/'files'/relative
        if path.is_symlink() or digest(path.read_bytes())!=expected:raise ValueError('Changed execution file is unavailable or modified')
    if destination.exists():raise ValueError('Reconstruction requires a new isolated destination')
    destination.mkdir(parents=True,exist_ok=False)
    for relative in data['source_files']:
        out=destination/relative;out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/relative,out)
    for relative in data['removed_files']:(destination/relative).unlink()
    for relative in data['changed_files']:
        out=destination/relative;out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(manifest.parent/'files'/relative,out)
    return destination
