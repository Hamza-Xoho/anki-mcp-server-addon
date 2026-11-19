"""Fixed student-write boundary: compare and dispatch in one main-thread request.

Not a transaction against other processes, nor user/quality authorization. No
registry lookup, arbitrary tool forwarding, URL import or database writes.
"""
import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote
from pathlib import Path
from typing import Annotated, Any, Literal
from pydantic import Field

from ....handler_wrappers import HandlerError, get_col
from ....media_validators import sanitize_media_filename, validate_media_filename_type
from ....tool_decorator import Tool
from .collection_identity_tool import collection_identity
from .add_note_tool import add_note
from .update_note_fields_tool import update_note_fields
from .card_management.card_unsuspend_tool import card_unsuspend
from .card_management.card_suspend_tool import card_suspend
from .store_media_file_tool import store_media_file
from .read_media_file_tool import read_media_file

Operation = Annotated[Literal['add_note', 'update_note_fields', 'card_unsuspend', 'card_suspend', 'store_media_file'], Field(description='One of five fixed student operations')]
Arguments = Annotated[dict[str, Any], Field(description='Exact operation-specific arguments; no paths or URLs')]
Expected = Annotated[dict[str, Any], Field(description='Unmodified complete student_operation_state response reviewed for this request')]


def _refuse(message):
    raise HandlerError(message, code='conflict')


def _ids(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 100 or any(type(i) is not int or i <= 0 for i in values) or len(set(values)) != len(values):
        _refuse('Expected 1–100 unique positive card IDs')


def _validate(operation, arguments):
    required = {
        'add_note': {'deck_name', 'model_name', 'fields', 'tags'},
        'update_note_fields': {'id', 'fields'},
        'card_unsuspend': {'card_ids'},
        'card_suspend': {'card_ids'},
        'store_media_file': {'filename', 'data'},
    }
    if operation not in required or not isinstance(arguments, dict) or set(arguments) != required[operation]:
        _refuse('Unsupported student operation or arguments')
    if len(json.dumps(arguments).encode()) > 12 * 1024 * 1024:
        _refuse('Student operation exceeds request limit')
    if operation in ('add_note', 'update_note_fields'):
        fields = arguments['fields']
        if not isinstance(fields, dict) or not fields or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in fields.items()):
            _refuse('Complete field strings required')
    if operation == 'update_note_fields' and (type(arguments['id']) is not int or arguments['id'] <= 0):
        _refuse('Expected positive note ID')
    if operation in ('card_unsuspend', 'card_suspend'):
        _ids(arguments['card_ids'])
    if operation == 'add_note':
        if any(not isinstance(arguments[k], str) or not arguments[k] for k in ('deck_name', 'model_name')) or not isinstance(arguments['tags'], list) or any(not isinstance(t, str) for t in arguments['tags']):
            _refuse('Explicit deck, model and tags required')
    if operation == 'store_media_file':
        filename = arguments['filename']
        if not isinstance(filename, str) or sanitize_media_filename(filename) != filename:
            _refuse('Exact media filename required')
        validate_media_filename_type(filename)
        try:
            data = base64.b64decode(arguments['data'], validate=True)
        except (ValueError, TypeError) as exc:
            raise HandlerError('Invalid media bytes', code='validation_error') from exc
        if not data or len(data) > 8 * 1024 * 1024:
            _refuse('Media must contain 1 byte to 8 MiB')


def _card(card):
    return {**{key: getattr(card, key) for key in ('id', 'nid', 'did', 'ord', 'queue', 'type', 'due', 'mod')},
            'backend_sha256': hashlib.sha256(card._to_backend_card().SerializeToString(deterministic=True)).hexdigest()}


def _note(col, nid):
    note = col.get_note(nid)
    return {'id': note.id, 'fields': dict(note.items()), 'tags': list(note.tags),
            'mod': note.mod, 'model': note.note_type(),
            'cards': sorted((_card(c) for c in note.cards()), key=lambda c: c['id'])}


class _MediaReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.names=set()
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='img':
            self.names.update(value for key,value in attrs if key.lower()=='src' and value)


def _media_dependencies(col,operation,arguments,target):
    texts=list(arguments.get('fields',{}).values())
    notes=target if isinstance(target,list) else [target] if operation=='update_note_fields' else []
    pairs=[]
    for note in notes:
        texts.extend(note['fields'].values());pairs.append((note['model'],note['fields']))
    if operation=='add_note':pairs.append((target['model'],arguments['fields']))
    elif operation=='update_note_fields':pairs.append((target['model'],arguments['fields']))
    for model,fields in pairs:
        for template in model.get('tmpls',[]):
            for key in ('qfmt','afmt'):
                markup=template.get(key,'')
                def section(match):
                    name=match[2].strip()
                    if name not in fields:return match[3]
                    present=bool(re.sub(r'<[^>]+>|\s|&nbsp;','',fields[name]))
                    return match[3] if present!=(match[1]=='^') else ''
                for _ in range(3):markup=re.sub(r'\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}',section,markup,flags=re.S)
                markup=re.sub(r'\{\{([^{}]+)\}\}',lambda m:fields.get(m[1].split(':')[-1].strip(),''),markup)
                texts.append(markup)
    parser=_MediaReferences()
    for text in texts:
        parser.feed(text)
        parser.names.update(re.findall(r'\[sound:([^\]]+)\]',text))
    if len(parser.names)>100:_refuse('Too many referenced media files for complete state')
    result={}
    for raw in sorted(parser.names):
        if raw.startswith('data:'):continue
        if re.match(r'^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)',raw):
            result[raw]={'external':True};continue
        name=unquote(raw)
        if sanitize_media_filename(name)!=name:_refuse('Unsupported referenced media filename')
        path=Path(col.media.dir())/name
        if not path.exists() and not path.is_symlink():result[name]=None
        else:
            observed=read_media_file(name)
            result[name]={k:observed[k] for k in ('filename','size','sha256')}
    return result


@Tool('student_operation_state', 'Read complete bounded state for one fixed student operation. This is not authorization.', title='Student Operation State')
def student_operation_state(operation: Operation, arguments: Arguments) -> dict[str, Any]:
    _validate(operation, arguments)
    identity = collection_identity()
    if not identity.get('identity_complete') or not identity.get('collection_session') or not identity.get('identity_sha256'):
        _refuse('Complete profile binding and initialized runtime session required')
    binding = {k: identity[k] for k in ('profile_name', 'collection_path', 'collection_created_ts', 'identity_sha256', 'collection_session')}
    col = get_col()
    if operation == 'update_note_fields':
        target = _note(col, arguments['id'])
        if set(arguments['fields']) != set(target['fields']):
            _refuse('Complete model fields required')
    elif operation in ('card_unsuspend', 'card_suspend'):
        cards = [col.get_card(cid) for cid in arguments['card_ids']]
        target = [_note(col, nid) for nid in sorted({c.nid for c in cards})]
    elif operation == 'add_note':
        model = col.models.by_name(arguments['model_name'])
        deck = col.decks.by_name(arguments['deck_name'])
        if not model or not deck:
            _refuse('Selected deck or model is missing')
        if set(arguments['fields']) != {f['name'] for f in model['flds']}:
            _refuse('Complete model fields required')
        # Use Anki native duplicate semantics. Unlike the historical primitive,
        # a failed duplicate check cannot fall through to mutation here.
        from anki.notes import Note
        candidate = Note(col, model)
        for name, value in arguments['fields'].items(): candidate[name] = value
        if candidate.fields_check() != 0:
            _refuse('Empty or duplicate note refused')
        target = {'model': model, 'deck': deck}
    else:
        path = Path(col.media.dir()) / arguments['filename']
        target = read_media_file(arguments['filename']) if path.exists() or path.is_symlink() else None
        if target is not None:
            target = {k: target[k] for k in ('filename', 'size', 'sha256')}
    result = {'version': 2, 'operation': operation, 'arguments': arguments, 'binding': binding, 'target': target,
              'media': _media_dependencies(col,operation,arguments,target)}
    # Roundtrip isolates the snapshot from mutable Anki model/deck dictionaries.
    encoded = json.dumps(result, sort_keys=True, allow_nan=False)
    if len(encoded.encode()) > 16 * 1024 * 1024:
        _refuse('Complete state exceeds limit; operation refused')
    return json.loads(encoded)


@Tool('conditional_student_operation', 'Compare exact profile/session/request/target state and dispatch one fixed write synchronously. Caller must separately enforce approval and quality.', title='Conditional Student Operation', write=True)
def conditional_student_operation(operation: Operation, arguments: Arguments, expected_state: Expected) -> dict[str, Any]:
    current = student_operation_state(operation, arguments)
    if current != expected_state:
        _refuse('Student operation state changed; review again')
    if operation == 'add_note':
        result = add_note(**arguments, allow_duplicate=False)
    elif operation == 'update_note_fields':
        result = update_note_fields(**arguments)
    elif operation == 'card_unsuspend':
        result = card_unsuspend(**arguments)
    elif operation == 'card_suspend':
        result = card_suspend(**arguments)
    else:
        if current['target'] is not None:
            expected_hash = hashlib.sha256(base64.b64decode(arguments['data'], validate=True)).hexdigest()
            if current['target']['sha256'] != expected_hash:
                _refuse('Existing media has different bytes; choose a new filename')
        result = store_media_file(**arguments)
        wanted = base64.b64decode(arguments['data'], validate=True)
        if result.get('filename') != arguments['filename']:
            raise HandlerError('Media write outcome is uncertain: companion renamed the file', code='uncertain')
        try:
            observed = read_media_file(arguments['filename'])
            verified = (observed['size'] == len(wanted) and
                        observed['sha256'] == hashlib.sha256(wanted).hexdigest() and
                        base64.b64decode(observed['data'], validate=True) == wanted)
        except Exception:
            verified = False
        if not verified:
            raise HandlerError('Media write outcome is uncertain: byte readback failed', code='uncertain')
    return {'version': 2, 'result': result, 'binding': current['binding']}
