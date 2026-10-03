from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

import munck_safety.app as app
from munck_safety.app import _EVENT_DB_FILENAME, _configure_evidence_dir, _parse_args
from munck_safety.config import Config


@pytest.fixture
def poc_config() -> Config:
    path = Path(__file__).resolve().parents[1] / "config" / "poc-single-camera.json"
    return Config.from_file(path)


def test_evidence_dir_sets_artifacts_and_database(poc_config: Config) -> None:
    _configure_evidence_dir(poc_config, " artifacts/run-001 ")

    assert poc_config.alarm.artifacts_dir == "artifacts/run-001"
    assert poc_config.dashboard.db_path == str(
        Path("artifacts/run-001") / _EVENT_DB_FILENAME
    )


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


def test_cli_rejects_empty_evidence_dir(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--evidence-dir", "  "])
    assert "--evidence-dir nao pode ser vazio." in capsys.readouterr().err


def test_main_wires_evidence_dir_to_components(
    poc_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_dir = "artifacts/integration-run"
    observed: dict[str, str] = {}
    store = Mock()
    dashboard = Mock()
    alarm = Mock()

    monkeypatch.setattr(app.Config, "from_file", lambda _: poc_config)
    monkeypatch.setattr(app, "configure_logging", lambda _: None)

    def make_store(path: str, retention_days: int) -> Mock:
        observed["store_path"] = path
        return store

    def make_dashboard(_, cfg, artifacts_dir: str) -> Mock:
        observed["dashboard_artifacts"] = artifacts_dir
        return dashboard

    def make_alarm(cfg, store) -> Mock:
        observed["alarm_artifacts"] = cfg.artifacts_dir
        return alarm

    monkeypatch.setattr(app, "EventStore", make_store)
    monkeypatch.setattr(app, "DashboardServer", make_dashboard)
    monkeypatch.setattr(app, "AlarmManager", make_alarm)
    monkeypatch.setattr(app, "HealthMonitor", lambda *args, **kwargs: Mock())
    monkeypatch.setattr(app, "RulesEngine", lambda *args, **kwargs: Mock())
    monkeypatch.setattr(app, "PersonDetector", lambda **kwargs: Mock(available=True))
    monkeypatch.setattr(app, "PPEMonitor", lambda *args, **kwargs: Mock())
    monkeypatch.setattr(app, "CameraCapture", lambda *args, **kwargs: Mock())

    def stop_before_loop(sig, handler) -> None:
        if sig == app.signal.SIGINT:
            handler(sig, None)

    monkeypatch.setattr(app.signal, "signal", stop_before_loop)

    assert app.main(["--config", "unused.json", "--evidence-dir", evidence_dir]) == 0
    assert observed == {
        "store_path": str(Path(evidence_dir) / _EVENT_DB_FILENAME),
        "dashboard_artifacts": evidence_dir,
        "alarm_artifacts": evidence_dir,
    }
