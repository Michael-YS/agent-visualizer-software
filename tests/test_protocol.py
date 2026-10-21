import json
from pathlib import Path

from app.protocol import main, status_schema


def test_saved_schema_matches_bridge_model() -> None:
    path = Path(__file__).resolve().parents[1] / "status.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == status_schema()


def test_validator_normalizes_defaults_without_network(tmp_path, capsys) -> None:
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"id": "test-1", "name": "Test", "host": "pc", "state": "idle"}))
    assert main(["validate", str(path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["detail"] == ""
    assert isinstance(status["timestamp"], int)


def test_validator_rejects_byte_overflow_and_does_not_echo_input(tmp_path, capsys) -> None:
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"id": "test-1", "name": "Test", "host": "pc", "state": "idle", "detail": "界" * 200}), encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "界" not in output.err


def test_schema_check_detects_drift(tmp_path) -> None:
    path = tmp_path / "schema.json"
    path.write_text("{}")
    assert main(["schema", "--check", str(path)]) == 1


def test_validator_counts_json_escaping_in_total_limit(tmp_path) -> None:
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"id": "test-1", "name": '"' * 96, "host": '"' * 96, "state": "idle", "detail": "\\" * 512}))
    assert main(["validate", str(path)]) == 1
