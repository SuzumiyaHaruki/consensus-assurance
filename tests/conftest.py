from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def go_module(tmp_path):
    """A dependency-free module with distinct directory and package names."""
    root=tmp_path/'go-module'
    root.mkdir()
    (root/'go.mod').write_text('module example.org/local\n\ngo 1.20\n')
    (root/'README.md').write_text('For 0 <= value <= limit, Step must return within [0, limit].\n')
    for directory,package in [('.', 'service'),('internal/core','engine'),('internal/store','storage')]:
        folder=root/directory;folder.mkdir(parents=True,exist_ok=True)
        (folder/'value.go').write_text(f'package {package}\nfunc Step(value, limit int) int {{\n return value + 1\n}}\n')
    return root


@pytest.fixture
def rust_workspace(tmp_path):
    """A local Cargo dependency, build script and dev-feature unification."""
    root=tmp_path/'rust-workspace';(root/'sample/src').mkdir(parents=True)
    (root/'Cargo.toml').write_text('[workspace]\nmembers=["sample","increment"]\nresolver="2"\n')
    (root/'sample/Cargo.toml').write_text('[package]\nname="sample"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nincrement={path="../increment"}\n[dev-dependencies]\nincrement={path="../increment",features=["instrumented"]}\n')
    (root/'sample/src/lib.rs').write_text('pub fn step(value: i64, _limit: i64) -> i64 {\n    value + increment::value()\n}\n')
    (root/'increment/src').mkdir(parents=True)
    (root/'increment/Cargo.toml').write_text('[package]\nname="increment"\nversion="0.1.0"\nedition="2021"\n[features]\ninstrumented=[]\nalternate=[]\n')
    (root/'increment/src/lib.rs').write_text('pub fn value() -> i64 { if cfg!(feature="alternate") { 2 } else { 1 } }\n')
    (root/'increment/build.rs').write_text('fn main() { println!("cargo:rerun-if-changed=build.rs"); }\n')
    return root
