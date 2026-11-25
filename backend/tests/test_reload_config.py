from pathlib import Path

from uvicorn.config import Config
from uvicorn.supervisors.watchfilesreload import FileFilter

from dev_server import RELOAD_EXCLUDES as DEV_RELOAD_EXCLUDES
from dev_server import RELOAD_INCLUDES as DEV_RELOAD_INCLUDES
from main import RELOAD_EXCLUDES, RELOAD_INCLUDES


def test_reload_excludes_local_memory_databases_and_python_caches():
    assert "memory" in RELOAD_EXCLUDES
    assert "*.sqlite*" in RELOAD_EXCLUDES
    assert "*.db" in RELOAD_EXCLUDES
    assert "__pycache__" in RELOAD_EXCLUDES
    assert RELOAD_INCLUDES == DEV_RELOAD_INCLUDES
    assert "*.py" in RELOAD_INCLUDES
    assert ".env" in RELOAD_INCLUDES
    assert "memory" in DEV_RELOAD_EXCLUDES


def test_reload_filter_watches_dotenv_and_python_source_but_not_other_hidden_files(tmp_path):
    config = Config(
        "main:app",
        reload=True,
        reload_dirs=[tmp_path],
        reload_includes=DEV_RELOAD_INCLUDES,
        reload_excludes=DEV_RELOAD_EXCLUDES,
    )
    file_filter = FileFilter(config)

    assert file_filter(tmp_path / ".env")
    assert file_filter(tmp_path / "main.py")
    assert not file_filter(tmp_path / ".gitignore")
