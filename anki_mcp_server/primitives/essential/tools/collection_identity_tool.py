"""Read-only fingerprint of the open Anki profile and collection.

The fingerprint is a corroborating check, not a unique identifier. See the
``limits`` field in the response and tests/unit/test_collection_identity.py.
"""
import hashlib
import json
import os
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ....collection_session import token as session_token
from ....tool_decorator import Tool
from ....handler_wrappers import get_col, get_mw


_LIMITS = [
    "NON-UNIQUE and insufficient by itself to authorize mutations; a separate gate is required.",
    "identity_sha256 covers profile_name, collection_path and collection_created_ts only.",
    "collection_created_ts is copied with a collection file, so a copy at the same path and profile name is indistinguishable.",
    "A profile switched away and back to the same name and path produces the same identity_sha256; collection_session changes on lifecycle close/open.",
    "collection_session is runtime freshness only, null without observed lifecycle initialization; it is not persistent collection identity.",
    "An in-place restore without lifecycle events or a replaced Collection object can be invisible; fresh target-state checks are still required.",
    "modified_ts changes on any write and is state, not identity; it is excluded from identity_sha256.",
    "The response does not prove that the intended profile is open; the owner's profile selection remains the control.",
]


@Tool(
    "collection_identity",
    "Report the open Anki profile name, collection path and collection creation "
    "timestamp, with a SHA-256 fingerprint over those three values and the "
    "limits of that fingerprint. Read-only; it changes nothing in the collection.",
    title="Collection Identity",
)
def collection_identity() -> dict[str, Any]:
    col = get_col()
    mw = get_mw()

    profile_name = getattr(getattr(mw, "pm", None), "name", None)
    if not isinstance(profile_name, str) or not profile_name.strip():
        profile_name = None
    raw_path = getattr(col, "path", None)
    try:
        collection_path = os.fspath(raw_path)
    except TypeError:
        collection_path = None
    if not isinstance(collection_path, str) or not (
        PurePosixPath(collection_path).is_absolute() or PureWindowsPath(collection_path).is_absolute()
    ):
        collection_path = None
    created_ts = getattr(col, "crt", None)
    if type(created_ts) is not int or created_ts < 0:
        created_ts = None
    modified_ts = getattr(col, "mod", None)
    if type(modified_ts) is not int or modified_ts < 0:
        modified_ts = None
    identity_fields = {
        "profile_name": profile_name,
        "collection_path": collection_path,
        "collection_created_ts": created_ts,
    }
    missing = [name for name, value in identity_fields.items() if value is None]

    fingerprint_input = json.dumps(
        identity_fields,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity_sha256 = None if missing else hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()

    return {
        "profile_name": profile_name,
        "collection_path": collection_path,
        "collection_created_ts": created_ts,
        "modified_ts": modified_ts,
        "identity_sha256": identity_sha256,
        "collection_session": session_token(col) if not missing else None,
        "identity_is_unique": False,
        "identity_complete": not missing,
        "missing_identity_fields": missing,
        "limits": list(_LIMITS),
    }
