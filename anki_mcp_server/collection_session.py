"""Main-thread runtime freshness, never a persistent or unique collection ID.

Profile lifecycle events and replacement Collection objects invalidate bindings.
All functions run on Anki's Qt thread, like the tool handlers using them.
"""
from uuid import uuid4
import weakref

_epoch = None
_collection = None
_token = None


def begin(*args):
    global _epoch, _collection, _token
    _epoch, _collection, _token = uuid4().hex, None, None


def end(*args):
    global _epoch, _collection, _token
    _epoch, _collection, _token = None, None, None


def token(col):
    global _collection, _token
    if _epoch is None:
        return None
    if _collection is None or _collection() is not col:
        try:
            _collection = weakref.ref(col)
        except TypeError:
            _collection, _token = None, None
            return None
        _token = _epoch + ':' + uuid4().hex
    return _token


def install_hooks(hooks):
    hooks.profile_did_open.append(begin)
    hooks.profile_will_close.append(end)
    if hasattr(hooks, 'app_will_close'):
        hooks.app_will_close.append(end)
