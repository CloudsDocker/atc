"""Tests for config loading, saving, updating, and deleting profiles."""

from pathlib import Path
import pytest
from atc.config import Config, Profile, delete_profile, load, save_profile, set_default_profile
from atc.core.errors import AtcError


def test_save_new_profile_and_load(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    conf = save_profile(
        "dev06",
        {"type": "k8s", "context": "mqu-eks-dev", "namespace": "airflow3-dev06", "port": 8080},
        is_default=True,
        path=cfg_file,
    )
    assert conf.default == "dev06"
    assert "dev06" in conf.profiles
    p = conf.profiles["dev06"]
    assert p.type == "k8s"
    assert p.options["context"] == "mqu-eks-dev"
    assert p.options["namespace"] == "airflow3-dev06"
    assert p.options["port"] == 8080


def test_save_sibling_profile_preserves_existing(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    save_profile(
        "dev06",
        {"type": "k8s", "context": "mqu-eks-dev", "namespace": "airflow3-dev06"},
        path=cfg_file,
    )
    conf = save_profile(
        "dev01",
        {"type": "k8s", "context": "mqu-eks-dev", "namespace": "airflow3-dev01"},
        path=cfg_file,
    )
    assert set(conf.profiles.keys()) == {"dev06", "dev01"}
    assert conf.default == "dev06"
    assert conf.profiles["dev01"].options["namespace"] == "airflow3-dev01"


def test_update_profile_in_place(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '# Header comment\ndefault = "dev06"\n\n'
        '# Dev06 profile\n[profiles.dev06]\ntype = "k8s"\nnamespace = "old-ns"\n'
    )
    conf = save_profile(
        "dev06",
        {"type": "k8s", "namespace": "airflow3-dev06", "readonly": True},
        path=cfg_file,
    )
    assert conf.profiles["dev06"].options["namespace"] == "airflow3-dev06"
    assert conf.profiles["dev06"].readonly is True
    # Verify comment preserved
    raw = cfg_file.read_text()
    assert "# Header comment" in raw


def test_rename_profile(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    save_profile(
        "dev06",
        {"type": "k8s", "context": "mqu-eks-dev"},
        is_default=True,
        path=cfg_file,
    )
    conf = save_profile(
        "dev01",
        {"type": "k8s", "context": "mqu-eks-dev", "namespace": "airflow3-dev01"},
        old_name="dev06",
        path=cfg_file,
    )
    assert "dev06" not in conf.profiles
    assert "dev01" in conf.profiles
    assert conf.default == "dev01"


def test_delete_profile(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    save_profile("dev06", {"type": "k8s"}, is_default=True, path=cfg_file)
    save_profile("dev01", {"type": "k8s"}, path=cfg_file)

    conf = delete_profile("dev06", path=cfg_file)
    assert "dev06" not in conf.profiles
    assert "dev01" in conf.profiles
    assert conf.default == "dev01"


def test_set_default_profile(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    save_profile("dev06", {"type": "k8s"}, is_default=True, path=cfg_file)
    save_profile("dev01", {"type": "k8s"}, path=cfg_file)

    conf = set_default_profile("dev01", path=cfg_file)
    assert conf.default == "dev01"
