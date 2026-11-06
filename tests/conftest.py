"""Load the plugin as package ``helm`` (its folder name has a dash) and give tests a fake ctx."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("helm", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
helm = importlib.util.module_from_spec(spec)
sys.modules["helm"] = helm
spec.loader.exec_module(helm)
from helm import core  # noqa: E402


class FakeCtx:
    """Records what the plugin registers; settings live in a plain dict."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.commands, self.hooks, self.posted = {}, {}, []
        self.choice = None  # what ask_choice returns

    def get_config(self, key, default=None):
        node = self.settings
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = handler

    def register_hook(self, name, fn, **kw):
        self.hooks.setdefault(name, []).append(fn)

    def fire(self, name, **kw):
        return [fn(**kw) for fn in self.hooks.get(name, [])]

    def ask_choice(self, question, choices):
        return self.choice

    def post_message(self, text):
        self.posted.append(text)

    def inject_message(self, content, role="user", *, session_key=None, origin=None):
        self.posted.append(("inject", session_key, content))
        return True


OWNER = {"user_id": "42"}


@pytest.fixture
def ctx(monkeypatch):
    """Fresh FakeCtx, in-memory DB, and a dict standing in for config.yaml."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE audit (ts REAL, key TEXT, old TEXT, new TEXT)")
    monkeypatch.setattr(core, "_db", conn)
    config: dict = {}

    def set_config(path, value):
        node = config
        for k in path.split(".")[:-1]:
            node = node.setdefault(k, {})
        node[path.split(".")[-1]] = value
        core.execute("INSERT INTO audit VALUES (0,?,?,?)", (path, "", str(value)))

    monkeypatch.setattr(core, "set_config", set_config)
    monkeypatch.setattr(core, "read_config", lambda: config)
    c = FakeCtx({"owner_ids": ["42"]})
    c.config = config
    return c
