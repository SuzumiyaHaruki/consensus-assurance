import hashlib
import json
import os
import re
from pathlib import Path
from consensus_assurance.core.types import Analysis, Record, uid


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def redact(text: str) -> str:
    text = re.sub(r"(?i)(authorization[\s:]+(?:bearer\s+)?)[^\s\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+", r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,})\b", "[REDACTED]", text)
    return text


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.model_dump(mode="json") if isinstance(value, Record) else value
    temporary = path.with_name(path.name + "." + uid() + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: Analysis, event: str):
        event_id = uid()
        write_json(self.root / "history" / f"{event_id}.json", state)
        write_json(self.root / "state.json", state)
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "state_version": event_id}, ensure_ascii=False) + "\n")

    def load(self) -> Analysis:
        return Analysis.model_validate_json((self.root / "state.json").read_text())
