"""Real Anki 26.9.2 collection + packaged tool protocol, entirely in-memory transport.

No HTTP listener, real profile, host credentials, sync or real companion is used.
Qt queue dispatch is replaced by same-thread dispatch; this is not GUI/HTTP acceptance.
"""
import asyncio
import base64
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace

import aqt  # preload the host's dependencies before the vendored stack
from anki.collection import Collection


async def run(package_name):
    with tempfile.TemporaryDirectory(prefix='synthetic-') as temp:
        root = Path(temp)
        shutil.copytree('/artifact/addon', root / package_name)
        sys.path.insert(0, str(root))
        col = Collection(str(root / 'collection.anki2'))
        try:
            aqt.mw = SimpleNamespace(col=col, pm=SimpleNamespace(name='Synthetic'),
                addonManager=SimpleNamespace(getConfig=lambda name: {}))
            package = importlib.import_module(package_name)
            primitives = importlib.import_module(package_name + '.primitives')
            registry = importlib.import_module(package_name + '.handler_registry')
            freshness = importlib.import_module(package_name + '.collection_session')
            from mcp.server.fastmcp import FastMCP
            from mcp.shared.memory import create_connected_server_and_client_session
            server = FastMCP('isolated-companion')
            async def dispatch(name, args):
                return registry.execute(name, args)
            primitives.register_all_tools(server, dispatch)
            freshness.begin()
            trace = []
            async with create_connected_server_and_client_session(server) as client:
                tools = await client.list_tools()
                names = {t.name for t in tools.tools}
                assert {'collection_identity', 'add_note', 'notes_info', 'card_suspend', 'card_unsuspend'} <= names
                identity_meta = next(t for t in tools.tools if t.name == 'collection_identity')
                assert identity_meta.annotations.readOnlyHint
                async def call(name, arguments):
                    result = await client.call_tool(name, arguments)
                    trace.append({'name': name, 'arguments': arguments,
                                  'result': result.model_dump(mode='json', by_alias=True)})
                    assert not result.isError, trace[-1]
                    assert result.structuredContent is not None
                    return result.structuredContent
                first = await call('collection_identity', {})
                assert first['identity_complete'] and first['collection_session']
                assert not first['identity_is_unique']
                # Stock cloze is used only for compatibility mechanics, never product-type acceptance.
                added = await call('add_note', {'deck_name': 'Default', 'model_name': 'Cloze',
                    'fields': {'Text': 'Synthetic {{c1::alpha}} then {{c2::beta}}', 'Back Extra': 'Synthetic only'},
                    'tags': ['APLUS_ISOLATED'], 'allow_duplicate': False})
                nid = added['note_id']
                info = await call('notes_info', {'notes': [nid]})
                note = info['notes'][0]
                assert note['noteId'] == nid and len(note['cards']) == 2
                first_card, sibling = note['cards']
                await call('card_suspend', {'card_ids': [first_card]})
                assert col.get_card(first_card).queue == -1
                assert col.get_card(sibling).queue != -1
                await call('card_unsuspend', {'card_ids': [first_card]})
                assert col.get_card(first_card).queue != -1
                assert col.get_card(sibling).queue != -1
                after = await call('collection_identity', {})
                assert after['collection_session'] == first['collection_session']
                image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jY1kAAAAASUVORK5CYII=')
                stored = await call('store_media_file', {'filename': 'synthetic.png', 'data': base64.b64encode(image).decode()})
                media = await call('read_media_file', {'filename': stored['filename']})
                assert base64.b64decode(media['data'], validate=True) == image
                assert media['sha256'] == hashlib.sha256(image).hexdigest()
                assert media['size'] == len(image)
                # Same profile/path/creation values do not hide an observed close/reopen.
                freshness.end()
                freshness.begin()
                reopened = await call('collection_identity', {})
                assert reopened['identity_sha256'] == first['identity_sha256']
                assert reopened['collection_session'] != first['collection_session']
            print(json.dumps({'status': 'passed', 'aqt': importlib.metadata.version('aqt'),
                'anki': importlib.metadata.version('anki'), 'package': package_name,
                'source_version': package.__version__, 'transport': 'MCP memory streams; no HTTP',
                'synthetic_only': True, 'trace': trace}, indent=2))
        finally:
            col.close()


if __name__ == '__main__':
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else 'addon'))
