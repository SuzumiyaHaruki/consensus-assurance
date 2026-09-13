import os
import re
import subprocess
from pathlib import Path
from consensus_assurance.core.types import Snapshot
from .files import digest

ALLOWED_SUFFIXES = {".go", ".mod", ".sum", ".md", ".rst", ".py", ".tla", ".cfg", ".json", ".yaml", ".yml", ".toml"}
EXCLUDED_DIRS = {".git", ".codex", ".agents", ".ssh", ".aws", ".venv", "node_modules", "vendor", "runs", "__pycache__"}
SENSITIVE_NAME = re.compile(r"(?i)(credential|secret|token|password|(?:^|[._-])key(?:[._-]|$)|^\.env|^id_rsa|^auth\.)")
SENSITIVE_CONTENT = re.compile(rb"-----BEGIN (?:[A-Z ]*PRIVATE KEY)|(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})|(?i:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[\"'][^\"'\s]{8,}")


def git(repo: Path, *args):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def capture(repo: Path, destination: Path | None = None) -> Snapshot:
    repo = repo.resolve()
    if destination and destination.resolve().is_relative_to(repo):
        raise ValueError("Snapshot destination must be outside the original repository")
    contents, excluded = {}, []
    for folder, dirs, names in os.walk(repo, followlinks=False):
        kept = []
        for name in dirs:
            p = Path(folder) / name
            if name in EXCLUDED_DIRS or p.is_symlink():
                excluded.append(str(p.relative_to(repo)))
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = Path(folder) / name
            rel = str(path.relative_to(repo))
            if path.is_symlink() or SENSITIVE_NAME.search(name) or path.suffix not in ALLOWED_SUFFIXES or name in {"AGENTS.md", "SKILL.md"}:
                excluded.append(rel)
                continue
            if path.stat().st_size > 2_000_000:
                excluded.append(rel)
                continue
            data = path.read_bytes()
            if b"\0" in data or SENSITIVE_CONTENT.search(data):
                excluded.append(rel)
                continue
            contents[rel] = digest(data)
            if destination:
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    commit = git(repo, "rev-parse", "HEAD")
    return Snapshot(repo=str(repo), commit=commit, branch=git(repo, "branch", "--show-current") or None,
        dirty=(bool(git(repo, "status", "--porcelain")) if commit else None),
        files=contents, excluded=sorted(excluded))
