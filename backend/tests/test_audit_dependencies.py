import sys
from unittest.mock import Mock

from scripts import audit_dependencies


def test_audit_ignores_only_documented_ids_and_propagates_failure(tmp_path, monkeypatch):
    risks = tmp_path / "accepted.md"
    risks.write_text(
        "| CVE-2026-45829 (GHSA-f4j7-r4q5-qw2c; PYSEC-2026-311) | accepted |\n"
        "CVE-2026-45829 is mentioned again. CVE-2026-foo is not an ID.\n",
        encoding="utf-8",
    )
    requirements = tmp_path / "requirements.txt"
    run = Mock(return_value=Mock(returncode=1))
    monkeypatch.setattr(audit_dependencies.subprocess, "run", run)

    assert audit_dependencies.audit(risks, requirements) == 1
    run.assert_called_once_with(
        [sys.executable, "-m", "pip_audit", "-r", str(requirements),
         "--ignore-vuln", "CVE-2026-45829", "--ignore-vuln", "GHSA-f4j7-r4q5-qw2c",
         "--ignore-vuln", "PYSEC-2026-311"],
        check=False,
    )
