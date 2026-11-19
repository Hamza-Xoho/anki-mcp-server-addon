"""Unit tests for the read-only ``collection_identity`` tool.

The fingerprint is corroborating evidence, not a unique identifier. The
``*_documented_limit`` tests pin the limits the tool reports, so a later change
that claims uniqueness fails here.

The tool is taken from the real registry (via the ``real_mcp`` fixture) rather
than imported by path: registering a ``@Tool`` twice raises, so a second import
of the module would break the rest of the suite.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import anki_mcp_server  # noqa: F401 -- triggers vendor path setup (see conftest.py)

from anki_mcp_server.handler_wrappers import HandlerError  # noqa: E402
from anki_mcp_server.tool_decorator import _registry  # noqa: E402


def _collection(path="/profiles/Main/collection.anki2", crt=1700000000, mod=1700000100):
    col = MagicMock(name="collection")
    col.path = path
    col.crt = crt
    col.mod = mod
    return col


def _mw(profile="Main"):
    return SimpleNamespace(pm=SimpleNamespace(name=profile))


@pytest.fixture
def identity_tool(real_mcp):
    """The registered tool function, after real primitives are loaded."""
    return _registry["collection_identity"]["original"]


@pytest.fixture
def open_collection(monkeypatch, identity_tool):
    """Install a fake open collection and main window for the tool to read.

    Patches the names the tool looks up in its own module globals, so it works
    however the module was loaded.
    """
    tool_globals = identity_tool.__globals__

    def install(col, mw):
        monkeypatch.setitem(tool_globals, "get_col", lambda: col)
        monkeypatch.setitem(tool_globals, "get_mw", lambda: mw)

    return install


def _identity(open_collection, identity_tool, *, profile="Main", **collection_kwargs):
    open_collection(_collection(**collection_kwargs), _mw(profile))
    return identity_tool()


def test_registered_as_read_only_tool(real_mcp):
    assert "collection_identity" in _registry
    assert _registry["collection_identity"]["write"] is False


def test_returns_documented_fields(open_collection, identity_tool):
    result = _identity(open_collection, identity_tool)
    assert set(result) == {
        "profile_name",
        "collection_path",
        "collection_created_ts",
        "modified_ts",
        "identity_sha256",
        "identity_is_unique",
        "limits",
    }
    assert result["profile_name"] == "Main"
    assert result["collection_path"] == "/profiles/Main/collection.anki2"
    assert result["collection_created_ts"] == 1700000000
    assert result["modified_ts"] == 1700000100
    assert result["identity_is_unique"] is False


def test_fingerprint_matches_independent_computation(open_collection, identity_tool):
    result = _identity(open_collection, identity_tool)
    expected_input = json.dumps(
        {
            "profile_name": "Main",
            "collection_path": "/profiles/Main/collection.anki2",
            "collection_created_ts": 1700000000,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert result["identity_sha256"] == hashlib.sha256(expected_input.encode()).hexdigest()


def test_fingerprint_is_stable_across_calls(open_collection, identity_tool):
    first = _identity(open_collection, identity_tool)
    second = _identity(open_collection, identity_tool)
    assert first["identity_sha256"] == second["identity_sha256"]


def test_modification_time_is_state_not_identity(open_collection, identity_tool):
    before = _identity(open_collection, identity_tool, mod=1700000100)
    after = _identity(open_collection, identity_tool, mod=1800000000)
    assert before["modified_ts"] != after["modified_ts"]
    assert before["identity_sha256"] == after["identity_sha256"]


def test_profile_rename_changes_fingerprint(open_collection, identity_tool):
    main = _identity(open_collection, identity_tool, profile="Main")
    renamed = _identity(open_collection, identity_tool, profile="Study")
    assert main["identity_sha256"] != renamed["identity_sha256"]


def test_collection_path_change_changes_fingerprint(open_collection, identity_tool):
    original = _identity(open_collection, identity_tool, path="/profiles/Main/collection.anki2")
    moved = _identity(open_collection, identity_tool, path="/profiles/Other/collection.anki2")
    assert original["identity_sha256"] != moved["identity_sha256"]


def test_created_timestamp_change_changes_fingerprint(open_collection, identity_tool):
    original = _identity(open_collection, identity_tool, crt=1700000000)
    recreated = _identity(open_collection, identity_tool, crt=1750000000)
    assert original["identity_sha256"] != recreated["identity_sha256"]


def test_identical_copy_at_same_path_is_indistinguishable_documented_limit(
    open_collection, identity_tool
):
    """A copy restored over the same path with the same profile name keeps
    every fingerprinted value, so the tool cannot tell it from the original."""
    original = _identity(open_collection, identity_tool)
    restored_copy = _identity(open_collection, identity_tool)
    assert original["identity_sha256"] == restored_copy["identity_sha256"]


def test_profile_switch_away_and_back_is_indistinguishable_documented_limit(
    open_collection, identity_tool
):
    original = _identity(
        open_collection, identity_tool, profile="Main", path="/profiles/Main/collection.anki2"
    )
    _identity(open_collection, identity_tool, profile="Study", path="/profiles/Study/collection.anki2")
    back = _identity(
        open_collection, identity_tool, profile="Main", path="/profiles/Main/collection.anki2"
    )
    assert original["identity_sha256"] == back["identity_sha256"]


def test_limits_state_the_non_uniqueness(open_collection, identity_tool):
    result = _identity(open_collection, identity_tool)
    text = " ".join(result["limits"]).lower()
    assert "non-unique" in text
    assert "insufficient by itself" in text
    assert "copied" in text
    assert "switched" in text
    assert "does not prove" in text


def test_missing_attributes_report_unknown_and_still_fingerprint(open_collection, identity_tool):
    open_collection(SimpleNamespace(), SimpleNamespace(pm=None))  # no path, crt or mod
    result = identity_tool()
    assert result["profile_name"] == "unknown"
    assert result["collection_path"] == "unknown"
    assert result["collection_created_ts"] is None
    assert result["modified_ts"] is None
    assert len(result["identity_sha256"]) == 64


def test_is_read_only_and_never_calls_collection_methods(open_collection, identity_tool):
    col = _collection()
    open_collection(col, _mw())
    identity_tool()
    assert col.mock_calls == []


def test_unavailable_collection_propagates_handler_error(monkeypatch, identity_tool):
    def no_collection():
        raise HandlerError("No collection is open", hint="Open a profile in Anki")

    monkeypatch.setitem(identity_tool.__globals__, "get_col", no_collection)
    with pytest.raises(HandlerError):
        identity_tool()
