"""Read-only fingerprint of the open Anki profile and collection.

The fingerprint is a corroborating check, not a unique identifier. See the
``limits`` field in the response and tests/unit/test_collection_identity.py.
"""
import hashlib
import json
from typing import Any

from ....tool_decorator import Tool
from ....handler_wrappers import get_col, get_mw


_LIMITS = [
    "NON-UNIQUE and insufficient by itself to authorize mutations; a separate gate is required.",
    "identity_sha256 covers profile_name, collection_path and collection_created_ts only.",
    "collection_created_ts is copied with a collection file, so a copy at the same path and profile name is indistinguishable.",
    "A profile switched away and back to the same name and path produces the same identity_sha256.",
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

    profile_name = getattr(getattr(mw, "pm", None), "name", None) or "unknown"
    raw_path = getattr(col, "path", None)
    collection_path = str(raw_path) if raw_path else "unknown"
    created_ts = getattr(col, "crt", None)
    modified_ts = getattr(col, "mod", None)

    fingerprint_input = json.dumps(
        {
            "profile_name": profile_name,
            "collection_path": collection_path,
            "collection_created_ts": created_ts,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    identity_sha256 = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()

    return {
        "profile_name": profile_name,
        "collection_path": collection_path,
        "collection_created_ts": created_ts,
        "modified_ts": modified_ts,
        "identity_sha256": identity_sha256,
        "identity_is_unique": False,
        "limits": list(_LIMITS),
    }
