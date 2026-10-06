from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, field_validator, model_validator
from .types import ActivityClass, Record


class Budget(Record):
    '''Configuration for budget constraints in the system.'''
    agent_calls: int = Field(default=8, ge=0)
    revisions: int = Field(default=3, ge=0)
    repair_attempts: int = Field(default=4, ge=0)
    action_timeout: float = Field(default=120, gt=0)
    agent_turn_timeout: float = Field(default=900, gt=0)
    total_seconds: float = Field(default=900, gt=0)

    experiments: int = Field(default=4, ge=0)
    audit_units: int = Field(default=2, ge=0)

    semantic_reviews: int = Field(default=4, ge=0)
    graph_objects: int = Field(default=1000, ge=1)


class TargetConfig(Record):
    '''Configuration for the target environment.'''
    expected_module: str | None = None
    variant: str = ""
    analysis_roots: list[str] = []
    execution_package: str = "."
    harness_path: str | None = None

    @model_validator(mode="after")
    def relative_paths(self):
        paths=self.analysis_roots+[self.execution_package]+([self.harness_path] if self.harness_path else [])
        if any(not p or p.startswith('-') or Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
            raise ValueError("Target paths must stay within the relative repository namespace")
        return self


class CodexProvider(Record):
    id: str
    base_url: str
    env_key: str
    model_catalog_path: str | None = None

    @model_validator(mode="after")
    def connection(self):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',self.id) or self.id in {'openai','ollama','lmstudio','amazon-bedrock'}:
            raise ValueError('Custom provider id must be a nonreserved simple identifier')
        url=urlsplit(self.base_url)
        if (url.scheme!='https' or not url.hostname or url.username is not None or url.password is not None
                or '?' in self.base_url or '#' in self.base_url or any(c.isspace() or c=='\\' for c in self.base_url)):
            raise ValueError('Provider base_url must be HTTPS without credentials, query, fragment or whitespace')
        _ = url.port
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',self.env_key) or self.env_key.upper() in {
                'PATH','HOME','CODEX_HOME','TMPDIR','LANG','LC_ALL','JAVA_HOME','RUSTC','RUSTDOC','CARGO_HOME',
                'GOCACHE','GOMODCACHE','GOPROXY','GOSUMDB','GOTOOLCHAIN','GOFLAGS','SSL_CERT_FILE','SSL_CERT_DIR',
                'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'}:
            raise ValueError('Provider env_key must name a dedicated credential variable, not a runtime setting')
        return self


class Config(Record):
    '''Main configuration for the system.'''
    protocol: str = "none"
    execution_backend: str = "none"
    target: TargetConfig = TargetConfig()
    repo_path: str | None = None
    agent_backend: str = "codex"
    agent_reasoning_effort: str | None = None
    agent_model: str | None = None
    codex_provider: CodexProvider | None = None
    runs_dir: str = "runs"
    cargo_seed_cache_dir: str | None = None
    budget: Budget = Budget()
    activity_focus: list[ActivityClass] = []
    directed_question: str | None = None
    fixture: str | None = None
    execution_isolation: Literal["bwrap", "workspace"] = "bwrap"
    allow_experiments: bool = True
    allow_agent_materials: bool = True

    @field_validator('cargo_seed_cache_dir')
    @classmethod
    def seed_cache_path(cls, value):
        return str(Path(value).expanduser().absolute()) if value and value.strip() else value

    @model_validator(mode="after")
    def provider_selection(self):
        if self.cargo_seed_cache_dir is not None:
            if self.execution_backend != 'cargo' or not self.cargo_seed_cache_dir.strip():
                raise ValueError('cargo_seed_cache_dir requires the Cargo backend and a nonempty directory')
            cache = Path(self.cargo_seed_cache_dir)
            runs = Path(self.runs_dir).expanduser().resolve()
            if cache.is_relative_to(runs) or runs.is_relative_to(cache):
                raise ValueError('Cargo seed cache must be outside run directories')
        if self.codex_provider and (self.agent_backend!='codex' or not (self.agent_model or '').strip()):
            raise ValueError('A custom provider requires agent_backend=codex and an explicit agent_model')
        if self.codex_provider and (self.agent_model.startswith('-') or any(c.isspace() for c in self.agent_model)):
            raise ValueError('Custom provider agent_model must be a single model identifier')
        return self

    @model_validator(mode="before")
    @classmethod
    def reject_retired_tools(cls, value):
        budget = value.get('budget') if isinstance(value, dict) else None
        if isinstance(value, dict) and ({'verifier_backend', 'tlc_jar'} & value.keys() or
                isinstance(budget, dict) and {'model_checks', 'reachability_checks', 'trigger_retries'} & budget.keys()):
            raise ValueError("Integrated TLA/TLC is no longer supported; remove retired verifier and model budget settings for a new run")
        return value


def locate_repo(explicit: str | None, configured: str | None) -> Path:
    candidate = explicit or configured
    if not candidate:raise FileNotFoundError("Supply --repo or config.repo_path explicitly")
    path = Path(candidate).expanduser().resolve()
    if not path.is_dir():raise FileNotFoundError(f"Target directory does not exist: {path}; supply --repo")
    return path
