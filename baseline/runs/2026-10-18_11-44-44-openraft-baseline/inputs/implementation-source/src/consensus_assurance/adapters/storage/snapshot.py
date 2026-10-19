import os
import re
import hashlib
import subprocess
from pathlib import Path
from consensus_assurance.core.types import Snapshot
from .files import digest

EXCLUDED_DIRS = {".git", ".codex", ".agents", ".ssh", ".aws", ".venv", "runs", "__pycache__"}
SENSITIVE_NAME = re.compile(r"(?i)(credential|secret|token|password|private[._-]?key|^\.env|^id_rsa|^auth\.)")
# A data-key source module is not a credential file; its content is still screened.
KEY_NAME = re.compile(r"(?i)(?:^|[._-])key(?:[._-]|$)")
SOURCE_SUFFIXES = {".go", ".py", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".kt", ".scala", ".js", ".jsx", ".ts", ".tsx", ".swift"}
# Literal branch starts let the regex engine skip unrelated bytes in large binary logs.
SENSITIVE_FIELDS = tuple(bytes([first]) + tail
    for starts, tail in [(b"aA", rb"(?i:pi[_-]?key|ccess[_-]?token)"), (b"pP", rb"(?i:assword)")]
    for first in starts)
SENSITIVE_RULES = tuple(re.compile(rule) for rule in (
    rb"-----BEGIN [A-Z ]*PRIVATE KEY",
    rb"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}",
    b"|".join(field + rb"\s*[:=]\s*[\"'][^\"'\s]{8,}" for field in SENSITIVE_FIELDS)))
SENSITIVE_CONTENT = re.compile(b"|".join(rule.pattern for rule in SENSITIVE_RULES))
PENDING_PEM = re.compile(rb"-----BEGIN ([A-Z ]*)\Z")
PENDING_FIELD = re.compile(rb"(?:" + b"|".join(SENSITIVE_FIELDS) + rb")\s*(?:[:=]\s*(?:[\"'][^\"'\s]{0,7})?)?\Z")
MAX_SOURCE_BYTES = 16_000_000


def sensitive_chunks(chunks):
    """Preserve unfinished matches without retaining unbounded headers or whitespace."""
    tails = [b"", b"", b""]
    for block in chunks:
        for index, rule in enumerate(SENSITIVE_RULES):
            data = tails[index] + block
            if rule.search(data):return True
            tails[index] = data[-32:]
            if index == 0:
                match = PENDING_PEM.search(data)
                if match:tails[index] = b"-----BEGIN " + match.group(1)[-10:]
            elif index == 2:
                match = PENDING_FIELD.search(data)
                if match:tails[index] = re.sub(rb"\s+", b" ", match.group())
    return False


def screened_digest(path):
    """Return (digest, size) or an exclusion reason, using bounded read buffers."""
    path = Path(path)
    hasher, size = hashlib.sha256(), 0
    reason = 'credential-like content'
    with path.open('rb') as stream:
        if path.suffix == '.java':
            data = stream.read(MAX_SOURCE_BYTES + 1)
            if len(data) <= MAX_SOURCE_BYTES:
                return reason if sensitive_file(path, data) else (digest(data), len(data))
            # Oversized Java sources retain strict screening, without whole-AST exemptions.
            del data
            stream.seek(0)
            reason = f'credential-like name or content; Java exception analysis is limited to {MAX_SOURCE_BYTES} bytes'
            if _private_name(path):return reason
        def blocks():
            nonlocal size
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(block)
                size += len(block)
                yield block
        if sensitive_chunks(blocks()):return reason
    return hasher.hexdigest(), size


def _private_name(path):
    return bool(SENSITIVE_NAME.search(path.name) or KEY_NAME.search(path.name) and path.suffix.lower() not in SOURCE_SUFFIXES)


def sensitive_file(path, data=None):
    """Screen credentials without mistaking Java types and property keys for secret data."""
    path=Path(path)
    private_name=_private_name(path)
    if data is None:return private_name and path.suffix!='.java'
    if path.suffix!='.java':return private_name or SENSITIVE_CONTENT.search(data) is not None
    matches=list(SENSITIVE_CONTENT.finditer(data))
    if private_name and path.suffix=='.java':
        matches.extend(re.finditer(rb'(?i:credentials?|secrets?|tokens?|(?:api|private)_?key)\s*=\s*"[^"\s]{8,}',data))
    if not private_name and not matches:return False
    from tree_sitter import Language, Parser
    import tree_sitter_java
    tree=Parser(Language(tree_sitter_java.language())).parse(data).root_node
    types={'class_declaration','interface_declaration','enum_declaration','record_declaration'}
    if tree.has_error or not any(n.type in types and n.child_by_field_name('name').text.decode()==path.stem for n in tree.named_children):
        return True
    # These short, conventional dummy passwords are allowed only in Java test sources.
    # Provider tokens and private-key markers remain excluded even there.
    test_source='src/test/java/' in path.as_posix()
    dummy=re.compile(r'(?i)(?:testpass(?:word)?|pa\$\$w0rd|password\d*|(?:root|admin)_passw?d|user(?:name)?\d*:pass(?:word)?\d*)')
    for match in matches:
        node=tree.descendant_for_byte_range(match.start(),match.end()-1)
        if node.type!='variable_declarator':return True
        name=node.child_by_field_name('name');value=node.child_by_field_name('value')
        # A test password may be converted to char[] immediately after the literal.
        literal=value.child_by_field_name('object') if value and value.type=='method_invocation' else value
        if literal is None or literal.type!='string_literal':return True
        content=literal.text.decode()[1:-1]
        if test_source and dummy.fullmatch(content):continue
        if name is None or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){2,}',content):return True
        nodes=[tree];property_key=False
        while nodes:
            call=nodes.pop();nodes.extend(call.named_children)
            if call.type!='method_invocation':continue
            owner=call.child_by_field_name('object');method=call.child_by_field_name('name');args=call.child_by_field_name('arguments')
            if owner and owner.text==b'System' and method and method.text==b'getProperty' and args and args.named_children:
                property_key |= args.named_children[0].text==name.text
        if not property_key:return True
    return False


def git(repo: Path, *args):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def fixed_submodules(repo):
    """Validate initialized gitlinks without fetching or following branch tips."""
    records = {}
    def visit(root, prefix=Path('.')):
        tree = git(root, 'ls-tree', '-rz', 'HEAD')
        if tree is None:
            if (root/'.git').exists():raise ValueError(f'Cannot inspect fixed Git tree: {root}')
            return
        for entry in tree.split('\0'):
            if not entry:continue
            meta, name = entry.split('\t', 1)
            mode, kind, expected = meta.split()
            if mode != '160000':continue
            relative = prefix / name
            child = root / name
            if Path(name).is_absolute() or '..' in Path(name).parts or any(
                    p.is_symlink() for p in [child, *child.parents] if p.is_relative_to(repo)):
                raise ValueError(f'Unsafe submodule path: {relative}')
            actual = git(child, 'rev-parse', 'HEAD') if (child/'.git').exists() else None
            if actual != expected:
                raise ValueError(f'Submodule {relative}: expected {expected}; actual {actual or "missing/uninitialized"}')
            status = git(child, 'status', '--porcelain', '--untracked-files=all')
            if status != '':
                raise ValueError(f'Submodule {relative}: expected {expected}; actual dirty or unreadable working tree')
            records[str(relative)] = expected
            visit(child, relative)
    visit(repo)
    return records


def capture(repo: Path, destination: Path | None = None, *, excluded_dirs=(), analysis_roots=(), expected_module=None) -> Snapshot:
    repo = repo.resolve()
    if destination and destination.resolve().is_relative_to(repo):
        raise ValueError("Snapshot destination must be outside the original repository")
    submodules = fixed_submodules(repo)
    tracked = {}
    for name in submodules:
        listing = git(repo/name, 'ls-files', '-z')
        if listing is None:raise ValueError(f'Cannot enumerate fixed submodule: {name}')
        tracked[name] = set(listing.split('\0'))
    contents, excluded, reasons, readable = {}, [], {}, []
    for folder, dirs, names in os.walk(repo, followlinks=False):
        kept = []
        for name in dirs:
            p = Path(folder) / name
            if name in EXCLUDED_DIRS or name in excluded_dirs or p.is_symlink():
                excluded.append(str(p.relative_to(repo)))
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = Path(folder) / name
            rel = str(path.relative_to(repo))
            owner = max((p for p in submodules if Path(rel).is_relative_to(p)), key=len, default=None)
            if owner and str(Path(rel).relative_to(owner)) not in tracked[owner]:continue
            if path.is_symlink() or sensitive_file(path) or name in {".git", "AGENTS.md", "SKILL.md"}:
                excluded.append(rel)
                reasons[rel] = "Excluded credential-like name, instruction file, symlink, oversize file or sensitive content"
                continue
            if path.stat().st_size > MAX_SOURCE_BYTES:
                excluded.append(rel)
                reasons[rel] = "Excluded credential-like name, instruction file, symlink, oversize file or sensitive content"
                continue
            data = path.read_bytes()
            if sensitive_file(path,data):
                excluded.append(rel)
                reasons[rel] = "Excluded credential-like name, instruction file, symlink, oversize file or sensitive content"
                continue
            contents[rel] = digest(data)
            try:
                data.decode("utf-8")
                if b"\0" not in data and len(data) <= 2_000_000:
                    if not analysis_roots or any(Path(rel).is_relative_to(root) for root in analysis_roots):readable.append(rel)
            except UnicodeDecodeError:
                pass

            if destination:
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(path.stat().st_mode & 0o777)
    if expected_module:
        module=(repo/"go.mod").read_text() if "go.mod" in contents else ""
        if not re.search(r"^module\s+"+re.escape(expected_module)+r"\s*$",module,re.M):
            raise ValueError("Source module differs from the explicit target.expected_module")
    commit = git(repo, "rev-parse", "HEAD")
    return Snapshot(repo=str(repo), commit=commit, branch=git(repo, "branch", "--show-current") or None,
        dirty=(bool(git(repo, "status", "--porcelain")) if commit else None),
        files=contents, excluded=sorted(excluded), readable_files=sorted(readable), exclusion_reasons=reasons, submodules=submodules)
