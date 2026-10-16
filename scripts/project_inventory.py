"""Count publishable files and physical lines; local archives are not runtime code."""
import ast
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parents[1]


def category(name):
    if name.startswith('baseline/runs/'):
        return 'baseline_run_artifacts'
    if name.startswith('baseline/acceptance/'):
        return 'baseline_acceptance'
    if name.startswith('runs/'):
        return 'ca_run_artifacts'
    if name.startswith('tests/baseline/') and name.endswith('.py'):
        return 'baseline_tests'
    if name.startswith('tests/support/') and name.endswith('.py'):
        return 'test_support'
    if name.startswith('tests/'):
        return 'ca_tests' if name.endswith('.py') else 'test_fixtures'
    if name.startswith('baseline/') and name.endswith('.py'):
        return 'baseline_function'
    if name.startswith('src/'):
        return 'ca_function' if name.endswith('.py') else 'method_resources'
    if name.startswith('configs/'):
        return 'public_configs'
    if name.startswith('scripts/'):
        return 'development_tools'
    if name.startswith(('docs/', 'baseline/')) or name in {'README.md', 'AGENTS.md'}:
        return 'documents'


# Include new publishable files; honor the same exclusions as Git.
names = subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '-c', '-o', '--exclude-standard', '-z']
).decode().split('\0')
stats, modules = {}, []
for name in sorted(set(names)):
    path = root / name
    group = category(name)
    if not group or not path.is_file():
        continue
    data = path.read_bytes()
    lines = data.splitlines() if b'\0' not in data else []
    entry = stats.setdefault(group, dict(files=0, bytes=0, lines=0, nonblank=0))
    entry['files'] += 1
    entry['bytes'] += len(data)
    entry['lines'] += len(lines)
    entry['nonblank'] += sum(bool(line.strip()) for line in lines)
    if group in {'ca_function', 'baseline_function', 'development_tools'} and path.suffix == '.py':
        tree = ast.parse(data)
        calls = sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)})
        modules.append(dict(path=name, lines=len(lines), calls=calls))
result = {
    'categories': stats,
    'largest_modules': sorted(modules, key=lambda m: m['lines'], reverse=True)[:12],
    'basis': 'Git tracked and nonignored files; physical lines, not logical statements; binary lines omitted. Local archives and caches are excluded.',
}
Path(sys.argv[1]).write_text(json.dumps(result, indent=2, ensure_ascii=False))
