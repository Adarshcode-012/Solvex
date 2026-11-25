import asyncio
import os
import subprocess
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import main

def test_job_deadline_stops_unfinished_call(monkeypatch):
    monkeypatch.setattr(main.settings, 'solvex_mock_ai', True)
    monkeypatch.setattr(main.settings, 'job_max_seconds', 0.03)
    monkeypatch.setattr(main, '_consume_global_solve_cap', lambda *_: None)

    async def never(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, 'solve_problem', never)
    with TestClient(main.app) as client:
        started = client.post('/solve/jobs', json={'problem': 'deadline'})
        import time
        time.sleep(0.1)
        snapshot = client.get('/solve/jobs/' + started.json()['job_id']).json()
    assert snapshot['status'] == 'failed'
    assert snapshot['error']['code'] == 'job_timeout'
