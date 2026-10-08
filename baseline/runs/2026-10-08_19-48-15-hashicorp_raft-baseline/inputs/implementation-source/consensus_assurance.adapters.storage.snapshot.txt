import os
import re
import subprocess
from pathlib import Path
from consensus_assurance.core.types import Snapshot
from .files import digest

EXCLUDED_DIRS = {".git", ".codex", ".agents", ".ssh", ".aws", ".venv", "runs", "__pycache__"}
SENSITIVE_NAME = re.compile(r"(?i)(credential|secret|token|password|private[._-]?key|^\.env|^id_rsa|^auth\.)")
# A data-key source module is not a credential file; its content is still screened.
KEY_NAME = re.compile(r"(?i)(?:^|[._-])key(?:[._-]|$)")
SOURCE_SUFFIXES = {".go", ".py", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".kt", ".scala", ".js", ".jsx", ".ts", ".tsx", ".swift"}
SENSITIVE_CONTENT = re.compile(rb"-----BEGIN (?:[A-Z ]*PRIVATE KEY)|(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})|(?i:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[\"'][^\"'\s]{8,}")


def git(repo: Path, *args):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def capture(repo: Path, destination: Path | None = None, *, excluded_dirs=(), analysis_roots=(), expected_module=None) -> Snapshot:
    repo = repo.resolve()
    if destination and destination.resolve().is_relative_to(repo):
        raise ValueError("Snapshot destination must be outside the original repository")
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
            if path.is_symlink() or (SENSITIVE_NAME.search(name) or (KEY_NAME.search(name) and path.suffix.lower() not in SOURCE_SUFFIXES)) or name in {"AGENTS.md", "SKILL.md"}:
                excluded.append(rel)
                reasons[rel] = "Excluded credential-like name, instruction file, symlink, oversize file or sensitive content"
                continue
            if path.stat().st_size > 16_000_000:
                excluded.append(rel)
                reasons[rel] = "Excluded credential-like name, instruction file, symlink, oversize file or sensitive content"
                continue
            data = path.read_bytes()
            if SENSITIVE_CONTENT.search(data):
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
        files=contents, excluded=sorted(excluded), readable_files=sorted(readable), exclusion_reasons=reasons)
