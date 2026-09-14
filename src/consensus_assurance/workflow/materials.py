import re
from pathlib import Path
from pydantic import Field
from consensus_assurance.core.types import Material, Record
from consensus_assurance.adapters.storage.files import digest


from consensus_assurance.core.proposals import ReadRequest


class ReadingPlan(Record):
    requests: list[ReadRequest] = Field(max_length=12)
    rationale: str
    related_ids: list[str] = []
    gap: str = ""


def catalogue(repo, snapshot, adapter=None):
    entries = []
    for rel in sorted(snapshot.readable_files if snapshot.readable_files is not None else snapshot.files):
        path = repo / rel
        lines = path.read_text(errors="replace").splitlines()
        symbols = [{"line": i+1, "declaration": line[:180]} for i, line in enumerate(lines)
                   if re.match(r"^(?:func |type |def |class )", line)]
        if adapter and hasattr(adapter,"symbol_hints"):
            symbols.extend(adapter.symbol_hints(rel, lines))
        entries.append({"file": rel, "lines": len(lines), "symbols": symbols[:100]})
    return entries


def material_kind(path, text):
    if path.endswith((".md", ".rst")):
        return "document_statement"
    if "_test" in path or path.startswith("test"):
        return "test_expectation"
    if "interface {" in text:
        return "interface_statement"
    return "code_observation"


def read_material(repo, snapshot, request):
    if request.file not in snapshot.files or (snapshot.readable_files is not None and request.file not in snapshot.readable_files):
        raise ValueError("Requested file is not in the sanitized snapshot")
    lines = (repo / request.file).read_text().splitlines()
    if request.end_line < request.start_line or request.end_line > len(lines):
        raise ValueError("Requested source range does not exist")
    text = "\n".join(lines[request.start_line-1:request.end_line])
    return Material(id=f"{request.file}:{request.start_line}:{request.end_line}", file=request.file,
        start_line=request.start_line, end_line=request.end_line,
        kind=material_kind(request.file, text), text=text, content_digest=snapshot.files[request.file])


def initial_materials(repo, snapshot, budget, knowledge):
    result, count = [], 0
    for rel in sorted(snapshot.readable_files if snapshot.readable_files is not None else snapshot.files, key=lambda f: (not f.endswith((".md", ".rst")), len(f), f)):
        if len(result) >= min(8, budget.material_chunks):
            break
        lines = (repo / rel).read_text().splitlines()
        if not lines:
            continue
        end = min(len(lines), 100)
        item = read_material(repo, snapshot, ReadRequest(file=rel, start_line=1, end_line=end, reason="Initial repository survey"))
        if count + len(item.text) > budget.material_chars // 3:
            continue
        result.append(item); count += len(item.text)
    if knowledge and len(result) < budget.material_chunks and count + len(knowledge) <= budget.material_chars:
        result.append(Material(id="protocol-knowledge", file="protocol-knowledge", start_line=1, end_line=len(knowledge.splitlines()),
            kind="protocol_candidate", text=knowledge, content_digest=digest(knowledge.encode())))
    return result


def add_reads(state, repo, reading, budget):
    chars = sum(len(m.text) for m in state.materials)
    new_ids = []
    for req in reading.requests:
        item = read_material(repo, state.snapshot, req)
        if item.id in {m.id for m in state.materials}:
            continue
        if len(state.materials) >= budget.material_chunks or chars + len(item.text) > budget.material_chars:
            state.gaps.append("Material reading budget reached; requested range remains unexplored: " + item.id)
            continue
        state.materials.append(item); chars += len(item.text); new_ids.append(item.id)
    state.unread_ranges = {}
    for file in state.snapshot.readable_files if state.snapshot.readable_files is not None else state.snapshot.files:
        try:
            length = len((repo / file).read_text().splitlines())
        except UnicodeDecodeError:
            continue
        covered = sorted((m.start_line,m.end_line) for m in state.materials if m.file==file)
        cursor, missing = 1, []
        for start,end in covered:
            if cursor < start: missing.append([cursor,start-1])
            cursor = max(cursor,end+1)
        if cursor <= length: missing.append([cursor,length])
        if missing: state.unread_ranges[file] = missing
    state.unexplored = list(state.unread_ranges)
    state.reading_history.append({"related_ids":reading.related_ids,"gap":reading.gap,"rationale":reading.rationale,
        "requests":[q.model_dump() for q in reading.requests],"added_material_ids":new_ids})
    return new_ids
