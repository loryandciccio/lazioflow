"""La suite ordinaria resta offline e non usa lo storico locale della demo."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["LAZIOFLOW_LIVE"] = "0"
os.environ["LAZIOFLOW_AI"] = "0"
_database_dir = TemporaryDirectory(prefix="lazioflow-tests-")
os.environ["LAZIOFLOW_DB"] = str(Path(_database_dir.name) / "poller.db")


def pytest_sessionfinish(session, exitstatus):
    _database_dir.cleanup()
os.environ["AI_REQUESTS_PER_MINUTE"] = "100000"
os.environ["API_REQUESTS_PER_MINUTE"] = "100000"
os.environ["LAZIOFLOW_API_KEY"] = ""
os.environ["LAZIOFLOW_ENV"] = "development"
