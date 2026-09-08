from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_inspection_benchmark_records_cold_and_warm_preparation(tmp_path: Path) -> None:
    output = tmp_path / "inspection-benchmark.json"
    script = Path(__file__).parents[1] / "tools" / "benchmark_inspection.py"

    process = subprocess.run(
        [sys.executable, str(script), "--modules", "3", "--output", str(output)],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    assert json.loads(process.stdout) == json.loads(output.read_text(encoding="utf-8"))
    report = json.loads(process.stdout)
    assert report["schema"] == "poly.inspection-benchmark/v1"
    assert report["fixture"] == {"maven_modules": 3, "maven_pom_files": 4}
    assert report["preparation"]["cold"]["cache_state"] == "cold"
    assert report["preparation"]["warm"]["cache_state"] == "hit"
    assert report["preparation"]["equivalent"] is True
    assert report["maven_execution"] == {"included": False, "elapsed_ms": None}
