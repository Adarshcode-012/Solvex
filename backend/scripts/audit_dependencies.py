import re
import subprocess
import sys
from pathlib import Path


ADVISORY_ID = re.compile(
    r"\b(?:CVE-\d{4}-\d{4,}|GHSA-(?:[23456789cfghjmpqrvwx]{4}-){2}"
    r"[23456789cfghjmpqrvwx]{4}|PYSEC-\d{4}-\d+)\b"
)


def audit(risks_path: Path, requirements_path: Path) -> int:
    advisory_ids = dict.fromkeys(ADVISORY_ID.findall(risks_path.read_text(encoding="utf-8")))
    command = [sys.executable, "-m", "pip_audit", "-r", str(requirements_path)]
    for advisory_id in advisory_ids:
        command.extend(("--ignore-vuln", advisory_id))
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.exit(audit(root / "docs/ACCEPTED_RISKS.md", root / "backend/requirements.txt"))
