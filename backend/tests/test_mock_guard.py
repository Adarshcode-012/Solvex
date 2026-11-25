import asyncio
import os
import subprocess
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import main

def test_production_refuses_mock_startup():
    environment = {**os.environ, 'APP_ENV': 'production', 'SOLVEX_MOCK_AI': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True'}
    completed = subprocess.run([sys.executable, '-c', 'import main'], cwd=Path(__file__).resolve().parents[1], env=environment, text=True, capture_output=True)
    safe_lines = [line for line in completed.stderr.splitlines() if 'SOLVEX_MOCK_AI is forbidden in production' in line]
    if safe_lines:
        print('Startup refused: SOLVEX_MOCK_AI is forbidden in production')
    assert completed.returncode != 0
    assert safe_lines
