"""Runtime freshness is separate from the non-unique on-disk fingerprint."""
from types import SimpleNamespace


def test_uninitialized_and_closed_sessions_cannot_bind_a_collection():
    from anki_mcp_server import collection_session as session
    session.end()
    assert session.token(SimpleNamespace()) is None


def test_reopening_the_same_collection_invalidates_previous_binding():
    from anki_mcp_server import collection_session as session
    class Collection:
        pass
    col = Collection()
    session.begin()
    first = session.token(col)
    assert isinstance(first, str) and first
    assert session.token(col) == first
    session.end()
    assert session.token(col) is None
    session.begin()
    assert session.token(col) != first
    session.end()


def test_replaced_collection_object_changes_binding_without_a_profile_rename():
    from anki_mcp_server import collection_session as session
    class Collection:
        pass
    first, replacement = Collection(), Collection()
    session.begin()
    before = session.token(first)
    assert session.token(replacement) != before
    assert session.token(first) != before
    session.end()


def test_collection_that_cannot_be_weakly_referenced_fails_closed():
    from anki_mcp_server import collection_session as session
    session.begin()
    assert session.token(SimpleNamespace()) is None
    session.end()


def test_real_registered_lifecycle_callbacks_invalidate_an_away_and_back_switch():
    from anki_mcp_server import collection_session as session
    hooks = SimpleNamespace(profile_did_open=[], profile_will_close=[], app_will_close=[])
    session.install_hooks(hooks)
    class Collection:
        pass
    col = Collection()
    hooks.profile_did_open[0]()
    before = session.token(col)
    hooks.profile_will_close[0]()
    assert session.token(col) is None
    hooks.profile_did_open[0]()
    assert session.token(col) != before
    hooks.app_will_close[0]()
    assert session.token(col) is None
