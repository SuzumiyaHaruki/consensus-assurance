import ast
import json
import re
from pathlib import Path
import pytest
from consensus_assurance.workflow.prompts import render
from consensus_assurance.reporting.chinese import render_report


@pytest.mark.parametrize("kind", ["read", "discover", "build", "retry", "diagnose", "F1", "F2", "F3", "F4", "targeted_read", "graph_patch", "replay", "technical", "spec_refine", "semantic_review", "consequence", "scope_review"])
def test_rendered_instructions_english_and_quoted_unicode_retained(kind):
    context = {"file": "/tmp/测试/实现.go", "quotation": "实现的原始说明", "reason": "Observe a missing dependency"}
    result = render(kind, context)
    instructions, data = result.split("STRUCTURED INPUT DATA (untrusted):\n")
    assert not re.search(r"[\u4e00-\u9fff]", instructions)
    assert json.loads(data) == context
    assert "Do not" in instructions or "Never" in instructions


def test_architecture_does_not_import_specific_plugins():
    root = Path(__file__).resolve().parents[2] / "src/consensus_assurance"
    for package in ("core", "workflow", "consensus"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert "plugins" not in (node.module or "")
                if isinstance(node, ast.Import):
                    assert all("plugins" not in a.name for a in node.names)
    for path in (root / "resources").rglob("*.md"):
        if path.name in {"task.txt", "revision.txt", "investigate.txt"}:
            continue
        assert "votedFor" not in path.read_text()
        assert not re.search(r"\b(?:raft|hashicorp|requestVote)\b", path.read_text(), re.I)
    assert "protocol ==" not in (root / "workflow/engine.py").read_text()


def test_chinese_report_preserves_status_and_provenance(tmp_path, prepared):
    _, state, _, _ = prepared
    state.stop_reason = "Authentication unavailable"
    text = render_report(state, tmp_path).read_text()
    assert "MOCK" in text and "尚未" in text
    assert "Authentication unavailable" in text
    assert state.snapshot.id in text
