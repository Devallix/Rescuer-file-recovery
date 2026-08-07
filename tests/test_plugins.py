from pathlib import Path

import pytest

from rescuer.core.database import Config, Database
from rescuer.engine.plugins.manager import (
    HOOK_EVENTS,
    PluginManager,
    RescuerPlugin,
)

SIMPLE_PLUGIN = '''
from rescuer.engine.plugins.manager import RescuerPlugin


class Plugin(RescuerPlugin):
    name = "hello"
    version = "1.0"
    description = "Logs scan events"

    def __init__(self):
        self.events = []

    def on_scan_started(self, scan_id, mode):
        self.events.append(("started", scan_id, mode))

    def on_scan_finished(self, scan_id, count):
        self.events.append(("finished", scan_id, count))

    def on_found(self, file_id, name):
        self.events.append(("found", file_id, name))
'''

BROKEN_PLUGIN = '''
import json
raise RuntimeError("boom")
'''

NAMED_PLUGIN = '''
from rescuer.engine.plugins.manager import RescuerPlugin


def setup(manager):
    p = RescuerPlugin()
    p.name = "setup-driven"
    p.description = "created via setup"
    return p
'''


@pytest.fixture()
def plugins_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "hello_plugin.py").write_text(SIMPLE_PLUGIN, encoding="utf-8")
    (d / "setup_plugin").mkdir()
    (d / "setup_plugin" / "plugin.py").write_text(NAMED_PLUGIN, encoding="utf-8")
    (d / "broken_plugin.py").write_text(BROKEN_PLUGIN, encoding="utf-8")
    (d / "not_plugin.py").write_text("value = 42\n", encoding="utf-8")
    return d


@pytest.fixture()
def manager(plugins_dir: Path, tmp_path: Path) -> PluginManager:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    config = Config(db)
    return PluginManager(config, plugins_dir)


def test_discover_lists(manager: PluginManager):
    listed = manager.discover()
    names = {p["name"] for p in listed}
    assert names == {"hello", "setup-driven"}
    by_name = {p["name"]: p for p in listed}
    assert by_name["hello"]["version"] == "1.0"
    assert by_name["hello"]["enabled"] is False


def test_broken_plugin_recorded(manager: PluginManager):
    manager.discover()
    assert "broken_plugin" in manager.errors


def test_enable_disable_persist(manager: PluginManager):
    manager.discover()
    manager.set_enabled("hello", True)
    assert manager.enabled("hello")
    assert manager.get("hello") is not None
    assert manager._config.get("plugins.enabled") == ["hello"]
    manager.set_enabled("hello", False)
    assert not manager.enabled("hello")


def test_emit_dispatches_to_enabled_only(manager: PluginManager):
    manager.discover()
    manager.set_enabled("hello", True)
    manager.emit("scan_started", scan_id=7, mode="quick")
    manager.emit("scan_finished", scan_id=7, count=3)
    plugin = manager.get("hello")
    assert ("started", 7, "quick") in plugin.events
    assert ("finished", 7, 3) in plugin.events

    manager.set_enabled("hello", False)
    before = len(plugin.events)
    manager.emit("found", file_id=1, name="x.txt")
    assert len(plugin.events) == before


def test_emit_unknown_event_raises(manager: PluginManager):
    with pytest.raises(ValueError):
        manager.emit("not_an_event")


def test_hook_events_list():
    assert "scan_started" in HOOK_EVENTS
    assert set(HOOK_EVENTS) == {
        "scan_started", "scan_finished", "found",
        "recovery_started", "recovery_finished",
    }


def test_erroring_hook_is_swallowed(manager: PluginManager):
    class BadPlugin(RescuerPlugin):
        name = "bad"

        def on_found(self, file_id, name):
            raise RuntimeError("nope")

    manager.discover()
    manager._plugins["bad"] = BadPlugin()
    manager.set_enabled("bad", True)
    manager.emit("found", file_id=1, name="a")
    assert "bad" in manager.errors
