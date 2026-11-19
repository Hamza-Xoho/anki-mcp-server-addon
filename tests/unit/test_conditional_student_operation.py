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
    card._to_backend_card = lambda: SimpleNamespace(SerializeToString=lambda **_: str(getattr(card,'ivl',0)).encode())
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
    args = {'id':17, 'fields':{'Front':'after','Back':'answer'}}
    expected = state('update_note_fields', args)
    if change == 'session': identity['collection_session'] = 'session-b'
    elif change == 'fields': note.front = 'foreign edit'
    else: card.queue = 0
    with pytest.raises(HandlerError, match='changed'):
        dispatch('update_note_fields', args, expected)
    assert sent == []

def test_unchanged_state_dispatches_exactly_one_fixed_operation(boundary):
    state, dispatch, _, _, _, sent = boundary
    args = {'id':17, 'fields':{'Front':'after','Back':'answer'}}
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
    with pytest.raises(HandlerError): state('update_note_fields', {'id':17,'fields':{'Front':'after','Back':'answer'}})


def test_scheduling_edit_with_same_mod_refuses_dispatch(boundary):
    state, dispatch, _, _, card, sent = boundary
    card.ivl=10
    args={'id':17,'fields':{'Front':'after','Back':'answer'}}
    expected=state('update_note_fields',args)
    card.ivl=20
    with pytest.raises(HandlerError, match='changed'):
        dispatch('update_note_fields',args,expected)
    assert not sent


def test_media_rename_is_uncertain_not_acknowledged(boundary, monkeypatch, tmp_path):
    import base64
    state, dispatch, _, _, _, _ = boundary
    g=state.__globals__
    monkeypatch.setitem(g,'get_col',lambda: SimpleNamespace(media=SimpleNamespace(dir=lambda:str(tmp_path))))
    monkeypatch.setitem(g,'store_media_file',lambda **kw:{'filename':'renamed.png'})
    args={'filename':'original.png','data':base64.b64encode(b'bytes').decode()}
    expected=state('store_media_file',args)
    with pytest.raises(HandlerError,match='uncertain'):
        dispatch('store_media_file',args,expected)


def test_conditional_media_mismatched_byte_readback_is_uncertain(boundary, monkeypatch, tmp_path):
    import base64
    state, dispatch, _, _, _, _ = boundary
    g=state.__globals__
    monkeypatch.setitem(g,'get_col',lambda: SimpleNamespace(media=SimpleNamespace(dir=lambda:str(tmp_path))))
    monkeypatch.setitem(g,'store_media_file',lambda **kw:{'filename':'original.png'})
    monkeypatch.setitem(g,'read_media_file',lambda filename: {'filename':filename,'size':5,'sha256':'0'*64,'data':base64.b64encode(b'wrong').decode()})
    args={'filename':'original.png','data':base64.b64encode(b'bytes').decode()}
    expected=state('store_media_file',args)
    with pytest.raises(HandlerError,match='uncertain'):
        dispatch('store_media_file',args,expected)


def test_partial_field_update_is_refused_before_mutation(boundary):
    state, dispatch, _, _, _, sent = boundary
    with pytest.raises(HandlerError, match='Complete'):
        expected = state('update_note_fields', {'id':17, 'fields':{'Front':'after'}})
        dispatch('update_note_fields', {'id':17, 'fields':{'Front':'after'}}, expected)
    assert not sent


def test_conditional_suspension_binds_scheduling_and_dispatches(boundary, monkeypatch):
    state, dispatch, _, _, card, _ = boundary
    card.queue = 0
    calls = []
    monkeypatch.setitem(state.__globals__, 'card_suspend', lambda **kw: calls.append(kw) or {'suspended_count':1})
    args = {'card_ids':[23]}
    expected = state('card_suspend', args)
    card.ivl = 2
    with pytest.raises(HandlerError, match='changed'):
        dispatch('card_suspend', args, expected)
    assert not calls
    current = state('card_suspend', args)
    assert dispatch('card_suspend', args, current)['result'] == {'suspended_count':1}
    assert calls == [args]


@pytest.mark.parametrize('location',['old_fields','new_fields'])
def test_referenced_media_byte_change_refuses_note_operation(boundary,monkeypatch,tmp_path,location):
    import base64,hashlib
    state,dispatch,_,note,_,sent=boundary
    original_col=state.__globals__['get_col']()
    monkeypatch.setitem(state.__globals__,'get_col',lambda:SimpleNamespace(get_note=original_col.get_note,get_card=original_col.get_card,media=SimpleNamespace(dir=lambda:str(tmp_path))))
    path=tmp_path/'review.png';path.write_bytes(b'old bytes')
    def read(filename):
        data=(tmp_path/filename).read_bytes()
        return {'filename':filename,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()}
    monkeypatch.setitem(state.__globals__,'read_media_file',read)
    if location=='old_fields':note.front='<img src="review.png">'
    args={'id':17,'fields':{'Front':'<img src="review.png">' if location=='new_fields' else 'after','Back':'answer'}}
    expected=state('update_note_fields',args)
    path.write_bytes(b'changed bytes')
    with pytest.raises(HandlerError,match='changed'):
        dispatch('update_note_fields',args,expected)
    assert not sent


def test_template_field_media_reference_binds_actual_file(boundary,monkeypatch,tmp_path):
    import base64,hashlib
    state,dispatch,_,note,_,sent=boundary
    original_col=state.__globals__['get_col']()
    monkeypatch.setitem(state.__globals__,'get_col',lambda:SimpleNamespace(get_note=original_col.get_note,get_card=original_col.get_card,media=SimpleNamespace(dir=lambda:str(tmp_path))))
    note.items=lambda:[('Front','question'),('Back','review.png')]
    note.note_type=lambda:{'id':1,'name':'Basic','flds':[{'name':'Front'},{'name':'Back'}], 'tmpls':[{'qfmt':'<img src="{{Back}}">','afmt':'{{Back}}'}],'css':''}
    path=tmp_path/'review.png';path.write_bytes(b'old bytes')
    def read(filename):
        data=(tmp_path/filename).read_bytes()
        return {'filename':filename,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()}
    monkeypatch.setitem(state.__globals__,'read_media_file',read)
    args={'id':17,'fields':{'Front':'new question','Back':'review.png'}}
    expected=state('update_note_fields',args);path.write_bytes(b'changed bytes')
    with pytest.raises(HandlerError,match='changed'):dispatch('update_note_fields',args,expected)
    assert not sent
