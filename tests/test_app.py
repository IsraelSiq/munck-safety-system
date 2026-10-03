from __future__ import annotations

from pathlib import Path

import pytest

from munck_safety.app import _configure_evidence_dir, _parse_args
from munck_safety.config import Config


@pytest.fixture
def poc_config() -> Config:
    path = Path(__file__).resolve().parents[1] / "config" / "poc-single-camera.json"
    return Config.from_file(path)


def test_evidence_dir_sets_artifacts_and_database(poc_config: Config) -> None:
    _configure_evidence_dir(poc_config, " artifacts/run-001 ")

    assert poc_config.alarm.artifacts_dir == "artifacts/run-001"
    assert poc_config.dashboard.db_path == str(Path("artifacts/run-001") / "events.db")


def test_evidence_dir_none_preserves_configured_paths(poc_config: Config) -> None:
    original_artifacts = poc_config.alarm.artifacts_dir
    original_database = poc_config.dashboard.db_path

    _configure_evidence_dir(poc_config, None)

    assert poc_config.alarm.artifacts_dir == original_artifacts
    assert poc_config.dashboard.db_path == original_database


def test_empty_evidence_dir_is_rejected(poc_config: Config) -> None:
    with pytest.raises(ValueError, match="nao pode ser vazio"):
        _configure_evidence_dir(poc_config, " ")


def test_cli_parses_evidence_dir() -> None:
    args = _parse_args(["--evidence-dir", "artifacts/run-001"])

    assert args.evidence_dir == "artifacts/run-001"
