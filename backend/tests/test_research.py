import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_oom_is_not_success(tmp_path):
    from backend.research.pilot import run_logged

    def out_of_memory():
        raise MemoryError("CUDA out of memory")

    output = tmp_path / "result.json"
    result = run_logged(out_of_memory, output, metadata={"mode": "train"})
    assert result["status"] == "failed"
    assert result["error_code"] == "out_of_memory"
    assert result["mode"] == "train"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"


def test_incomplete_training_cannot_pass_the_feasibility_gate():
    from backend.research.pilot import validate_training_result

    with pytest.raises(ValueError, match="incomplete"):
        validate_training_result({
            "optimizer_steps": 0, "adapter_changed": False, "reload_status": "not_run",
        }, expected_steps=20)


def test_training_configuration_cannot_silently_change_model_or_use_unpinned_weights():
    from backend.research.pilot import validate_config

    with pytest.raises(ValueError):
        validate_config({"model_id": "another/model", "revision": "main"})


def test_hardware_probe_reports_real_memory_and_disk():
    from backend.research.hardware_probe import probe

    result = probe()
    assert result["memory"]["total_bytes"] > 0
    assert result["disk"]["free_bytes"] > 0
    assert result["python"]["version"]
    assert "gpu" in result


def test_synthetic_fixture_has_three_readable_disciplines(tmp_path):
    from backend.research.make_fixture import make_fixture
    from backend.research.ifc_probe import inspect_ifc

    manifest = make_fixture(tmp_path)
    assert manifest["synthetic"] is True
    assert {item["discipline"] for item in manifest["files"]} == {"ARCH", "STR", "MEP"}
    for item in manifest["files"]:
        report = inspect_ifc(tmp_path / item["file"])
        assert report["status"] == "completed"
        assert report["element_count"] > 0


def test_pilot_report_cannot_overwrite_its_configuration(tmp_path):
    config = {
        "model_id": "Qwen/Qwen3-4B", "revision": "a" * 40,
        "max_steps": 20, "context_length": 256, "lora_rank": 4,
    }
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "backend.research.pilot", "train", "--config", str(path), "--output", str(path)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert json.loads(path.read_text(encoding="utf-8")) == config


def test_logged_experiment_preserves_existing_report_before_running(tmp_path):
    from backend.research.pilot import run_logged

    output = tmp_path / "existing.json"
    output.write_bytes(b'{"existing":true}')
    effects = []

    def operation():
        effects.append("ran")
        return {}

    with pytest.raises(FileExistsError):
        run_logged(operation, output)
    assert output.read_bytes() == b'{"existing":true}'
    assert effects == []
