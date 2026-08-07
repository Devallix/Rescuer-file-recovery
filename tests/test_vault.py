import json
from pathlib import Path

import pytest

from rescuer.core.database import Database
from rescuer.engine.vault import manager as vault_manager


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db", Path("rescuer/data/migrations"))


def test_create_and_list_vault(db):
    vid = vault_manager.create_vault(db, "C:\\Recovered", {"name": "Main"})
    assert vid > 0
    vaults = vault_manager.list_vaults(db)
    assert len(vaults) == 1
    assert vaults[0]["folder"] == "C:\\Recovered"
    assert vaults[0]["metadata"]["name"] == "Main"


def test_get_vault(db):
    vid = vault_manager.create_vault(db, "D:\\Out")
    row = vault_manager.get_vault(db, vid)
    assert row is not None
    assert row["folder"] == "D:\\Out"
    assert vault_manager.get_vault(db, 9999) is None


def test_delete_vault(db):
    vid = vault_manager.create_vault(db, "C:\\Temp")
    vault_manager.delete_vault(db, vid)
    assert vault_manager.get_vault(db, vid) is None
    remaining = vault_manager.list_vaults(db)
    assert len(remaining) == 0
