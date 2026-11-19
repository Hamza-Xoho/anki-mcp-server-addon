"""Conditional dispatch refuses stale queued state, using real registered tools."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from anki_mcp_server.tool_decorator import _registry
from anki_mcp_server.handler_wrappers import HandlerError

@pytest.fixture
def boundary(real_mcp, monkeypatch):
    assert 'student_operation_state' in _registry
    state = _registry['student_operation_state']['original']
    dispatch = _registry['conditional_student_operation']['original']
    globals_ = state.__globals__
    identity = dict(profile_name='Main', collection_path='/synthetic/collection.anki2',
                    collection_created_ts=1, identity_complete=True, collection_session='session-a', identity_sha256='a'*64)
    class Note:
        id = 17
        tags = ['keep']
        mod = 1
        def items(self): return [('Front', self.front), ('Back', 'answer')]
        def note_type(self): return {'id': 1, 'name': 'Basic', 'flds': [{'name':'Front'}, {'name':'Back'}]}
        def cards(self): return [card]
        front = 'before'
    note = Note()
    card = SimpleNamespace(id=23, nid=17, did=1, ord=0, queue=-1, type=0, due=0, mod=1)
    col = SimpleNamespace(get_note=lambda id: note, get_card=lambda id: card)
    sent = []
    monkeypatch.setitem(globals_, 'collection_identity', lambda: deepcopy(identity))
    monkeypatch.setitem(globals_, 'get_col', lambda: col)
    monkeypatch.setitem(globals_, 'update_note_fields', lambda **kw: sent.append(kw) or {'noteId':17})
    return state, dispatch, identity, note, card, sent

def test_conditional_dispatch_registered_as_mutating(real_mcp):
    assert 'conditional_student_operation' in _registry
    assert _registry['conditional_student_operation']['write']

@pytest.mark.parametrize('change', ['session', 'fields', 'sibling_state'])
def test_changed_state_refuses_before_mutation(boundary, change):
    state, dispatch, identity, note, card, sent = boundary
    args = {'id':17, 'fields':{'Front':'after'}}
    expected = state('update_note_fields', args)
    if change == 'session': identity['collection_session'] = 'session-b'
    elif change == 'fields': note.front = 'foreign edit'
    else: card.queue = 0
    with pytest.raises(HandlerError, match='changed'):
        dispatch('update_note_fields', args, expected)
    assert sent == []

def test_unchanged_state_dispatches_exactly_one_fixed_operation(boundary):
    state, dispatch, _, _, _, sent = boundary
    args = {'id':17, 'fields':{'Front':'after'}}
    expected = state('update_note_fields', args)
    assert dispatch('update_note_fields', args, expected)['result'] == {'noteId':17}
    assert sent == [args]

@pytest.mark.parametrize('operation,args', [
    ('delete_notes', {'notes':[17]}),
    ('store_media_file', {'filename':'x.png','path':'/etc/passwd'}),
    ('update_note_fields', {'id':17,'field_name':'Front','old_str':'x','new_str':'y'}),
    ('card_unsuspend', {'card_ids':[True]}),
])
def test_unsupported_arguments_fail_closed(boundary, operation, args):
    state, _, _, _, _, sent = boundary
    with pytest.raises(HandlerError): state(operation, args)
    assert sent == []

def test_incomplete_binding_refuses_even_with_matching_null_session(boundary):
    state, _, identity, _, _, _ = boundary
    identity['collection_session'] = None
    with pytest.raises(HandlerError): state('update_note_fields', {'id':17,'fields':{'Front':'after'}})
