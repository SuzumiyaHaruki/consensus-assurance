"""Small, strict configuration and CLI for the ordinary Codex baseline."""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from consensus_assurance.core.config import CodexProvider, TargetConfig


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    total_seconds: float = Field(default=7200, gt=0)
    agent_calls: int = Field(default=120, gt=0)
    agent_turn_timeout: float = Field(default=900, gt=0)
    action_timeout: float = Field(default=600, gt=0)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    baseline_id: Literal["codex_plain"] = "codex_plain"
    target_config: str
    repo_path: str | None = None
    agent_model: str
    agent_reasoning_effort: str | None
    codex_provider: CodexProvider | None = None
    auth_mode: Literal["codex_login", "api_key"]
    api_key_env: str | None = None
    runs_dir: str = "runs"
    allow_agent_materials: bool = False
    allow_experiments: bool = False
    go_mod_cache_dir: str | None = None
    cargo_dependency_cache_dir: str | None = None
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def validate_connection(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", self.agent_model):
            raise ValueError("agent_model must be one explicit identifier")
        if self.agent_reasoning_effort is not None and not re.fullmatch(r"[a-z]+", self.agent_reasoning_effort):
            raise ValueError("agent_reasoning_effort must be an explicit level or null")
        if self.codex_provider:
            if self.auth_mode != "api_key" or self.api_key_env is not None:
                raise ValueError("Custom providers use api_key and codex_provider.env_key only")
        elif self.auth_mode == "api_key":
            if not self.api_key_env:
                raise ValueError("Native API authentication requires api_key_env")
            CodexProvider(id="validation", base_url="https://example.org", env_key=self.api_key_env)
        elif self.api_key_env is not None:
            raise ValueError("codex_login must not configure an API credential")
        return self

    @property
    def credential_name(self):
        return self.codex_provider.env_key if self.codex_provider else self.api_key_env


def read_yaml(path):
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if key in result:
                raise ValueError(f"Duplicate configuration key: {key}")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    value = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a mapping")
    return value


def load_config(path):
    path = Path(path).expanduser().resolve()
    raw = read_yaml(path)
    config = Config.model_validate(raw)
    for name in ("target_config", "repo_path", "runs_dir", "go_mod_cache_dir", "cargo_dependency_cache_dir"):
        value = getattr(config, name)
        if value is not None:
            p = Path(value).expanduser()
            setattr(config, name, str((path.parent / p).resolve()))
    if config.codex_provider and config.codex_provider.model_catalog_path:
        p = Path(config.codex_provider.model_catalog_path).expanduser()
        config.codex_provider.model_catalog_path = str((path.parent / p).resolve())
    return config


def load_target(config):
    raw = read_yaml(config.target_config)
    if raw.get("execution_backend") not in {"go_module", "cargo"}:
        raise ValueError("Only go_module and cargo targets are supported")
    fields = {k: v for k, v in raw.get("target", {}).items()
              if k in {"variant", "expected_module", "execution_package", "analysis_roots"}}
    target = TargetConfig.model_validate(fields)
    return {"execution_backend": raw["execution_backend"], **target.model_dump(exclude={"harness_path"})}


def validate_selection(config):
    values = [config.agent_model]
    if config.codex_provider:
        values += [config.codex_provider.id, config.codex_provider.base_url]
    if any(re.search(r"(?i)(replace[_-]?me|fill[_-]?me|\.invalid\b|<|>)", v) for v in values):
        raise ValueError("Replace placeholder endpoint/model before invoking Codex")
    if not config.repo_path or not Path(config.repo_path).is_dir():
        raise ValueError("repo_path must identify an explicitly selected local repository")
    repo, runs = Path(config.repo_path), Path(config.runs_dir)
    if runs.is_relative_to(repo) or repo.is_relative_to(runs):
        raise ValueError("runs_dir and source repository must be disjoint")
    project = Path(__file__).resolve().parent.parent
    if repo == project or project.is_relative_to(repo):
        raise ValueError("The framework repository cannot be the audit target")
    return load_target(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description="普通 Codex 审计基线；默认不调用模型")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check-env", "run"):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        target = validate_selection(config)
        if args.command != "check-env" and not (config.allow_agent_materials and config.allow_experiments):
            raise ValueError("Set allow_agent_materials and allow_experiments explicitly before model use")
        from .runner import check_environment, run
        result = check_environment(config, target) if args.command == "check-env" else run(config, target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except ValidationError as exc:
        problems = [".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors(include_input=False)]
        print("配置无效：" + "; ".join(problems), file=sys.stderr)
        return 2
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"基线未启动：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
