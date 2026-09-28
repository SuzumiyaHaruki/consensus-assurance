"""Trusted local validator invocation and its read-only installation paths."""
import sys
import sysconfig
from pathlib import Path


def validation_tool(root):
    package_root = Path(__file__).resolve().parents[2]
    paths = list(dict.fromkeys([package_root, Path(sysconfig.get_path('purelib')),
        Path(sysconfig.get_path('platlib')), Path(sys.executable).parent, Path(sys.prefix) / 'pyvenv.cfg']))
    entry = ('import sys; sys.path.insert(0, ' + repr(str(package_root)) + '); '
        'from consensus_assurance.cli import main; raise SystemExit(main())')
    return {'command':[sys.executable, '-I', '-B', '-c', entry, 'validate', '--run', str(root), '--submission'],
        'read_only_paths':[str(p) for p in paths if p.exists()]}
