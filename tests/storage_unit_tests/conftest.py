# tests\storage_unit_tests\conftest.py
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import types
import duckdb
import pytest
import importlib

@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """
    Redirect paths.DATA_DIR and paths.OBJECTS_DIR to a temp folder so tests
    don't touch your real storage/.
    """
    # Import paths as a module so we can monkeypatch attributes
    paths = importlib.import_module("paths")
    data_dir = tmp_path / "storage" / "data"
    objects_dir = tmp_path / "storage" / "objects"
    data_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(paths, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(paths, "OBJECTS_DIR", objects_dir, raising=False)

    yield types.SimpleNamespace(DATA_DIR=data_dir, OBJECTS_DIR=objects_dir)

@pytest.fixture
def duck():
    return duckdb.connect(":memory:")
