"""Shared by every test file."""
import pytest


@pytest.fixture(autouse=True)
def designs_folder(tmp_path_factory, monkeypatch):
    """Copies of designs go to a throwaway folder, never the real Documents folder."""
    from app import config

    monkeypatch.setattr(config, "DESIGNS_DIR", tmp_path_factory.mktemp("designs"))
