import importlib.util
import logging
import sys
from pathlib import Path

from rescuer.core.database import Config
from rescuer.exceptions import PluginError
from rescuer.paths import Paths

log = logging.getLogger("rescuer.engine.plugins")

HOOK_EVENTS = ("scan_started", "scan_finished", "found", "recovery_started", "recovery_finished")

SETTINGS_KEY = "plugins.enabled"


class RescuerPlugin:
    """Base class for Rescuer plugins.

    Subclasses override the on_* hooks they care about. A plugin module must
    expose one of: a ``Plugin`` class subclassing RescuerPlugin, a module-level
    ``plugin`` instance, or a ``setup(manager)`` function returning a plugin.
    """

    name = ""
    version = "0.1"
    description = ""

    def on_scan_started(self, scan_id: int, mode: str) -> None: ...

    def on_scan_finished(self, scan_id: int, count: int) -> None: ...

    def on_found(self, file_id: int, name: str) -> None: ...

    def on_recovery_started(self, file_id: int) -> None: ...

    def on_recovery_finished(self, file_id: int, ok: bool) -> None: ...


def _load_plugin(module_path: Path) -> RescuerPlugin | None:
    try:
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        log.exception("failed to import plugin module %s", module_path)
        return None

    plugin = getattr(module, "plugin", None)
    if plugin is None:
        cls = getattr(module, "Plugin", None)
        if isinstance(cls, type) and issubclass(cls, RescuerPlugin) and cls is not RescuerPlugin:
            try:
                plugin = cls()
            except Exception as exc:
                log.exception("failed to instantiate plugin %s", module_path)
                return None
        else:
            setup = getattr(module, "setup", None)
            if callable(setup):
                try:
                    plugin = setup(None)
                except Exception as exc:
                    log.exception("failed to run setup for %s", module_path)
                    return None
    if not isinstance(plugin, RescuerPlugin):
        return None
    if not plugin.name:
        plugin.name = module_path.stem
    return plugin


class PluginManager:
    """Discovers plugins from a directory and dispatches hook events."""

    def __init__(self, config: Config, plugins_dir: Path | None = None) -> None:
        self._config = config
        self._dir = Path(plugins_dir) if plugins_dir is not None else Paths.plugins_dir
        self._plugins: dict[str, RescuerPlugin] = {}
        self._errors: dict[str, str] = {}

    @property
    def plugins_dir(self) -> Path:
        return self._dir

    def _enabled_names(self) -> set[str]:
        return set(self._config.get(SETTINGS_KEY, []) or [])

    def enabled(self, name: str) -> bool:
        return name in self._enabled_names()

    def set_enabled(self, name: str, enabled: bool) -> None:
        names = set(self._config.get(SETTINGS_KEY, []) or [])
        if enabled:
            names.add(name)
        else:
            names.discard(name)
        self._config.set(SETTINGS_KEY, sorted(names))

    def discover(self) -> list[dict]:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._plugins.clear()
        self._errors.clear()
        for path in sorted(self._dir.iterdir()):
            module_path: Path | None = None
            if path.is_file() and path.suffix == ".py":
                module_path = path
            elif path.is_dir() and (path / "plugin.py").is_file():
                module_path = path / "plugin.py"
            if module_path is None:
                continue
            plugin = _load_plugin(module_path)
            if plugin is None:
                self._errors[module_path.stem] = "Import or instantiation failed"
                continue
            self._plugins[plugin.name] = plugin
        return self.list_plugins()

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": name,
                "version": p.version,
                "description": p.description,
                "enabled": self.enabled(name),
            }
            for name, p in sorted(self._plugins.items())
        ]

    def get(self, name: str) -> RescuerPlugin | None:
        return self._plugins.get(name)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    def emit(self, event: str, **kwargs) -> None:
        if event not in HOOK_EVENTS:
            raise ValueError(f"Unknown plugin event: {event}")
        enabled = self._enabled_names()
        hook = f"on_{event}"
        for name, plugin in sorted(self._plugins.items()):
            if name not in enabled:
                continue
            try:
                getattr(plugin, hook)(**kwargs)
            except Exception as exc:
                log.exception("plugin %s hook %s failed", name, hook)
                self._errors[name] = f"{hook}: {exc}"

    def hook_events(self) -> list[str]:
        return list(HOOK_EVENTS)
