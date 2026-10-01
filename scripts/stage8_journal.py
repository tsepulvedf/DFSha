"""Pytest result journal; records outcomes, never exception bodies or request data."""
from datetime import datetime, timezone
import json
import os


def pytest_runtest_logreport(report):
    path = os.environ.get('DFSHA_TEST_JOURNAL')
    if path:
        with open(path, 'a', encoding='utf-8') as out:
            out.write(json.dumps(dict(test=report.nodeid, phase=report.when, outcome=report.outcome,
                duration_seconds=report.duration, time=datetime.now(timezone.utc).isoformat()))+'\n')
            out.flush()
            os.fsync(out.fileno())
