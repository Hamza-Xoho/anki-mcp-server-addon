"""Readback must prove bytes, reject alternate filenames, and bound responses."""
import base64
import hashlib
from types import SimpleNamespace

import pytest


def tool(real_mcp, monkeypatch, tmp_path):
    from anki_mcp_server.tool_decorator import _registry
    function = _registry['read_media_file']['original']
    monkeypatch.setitem(function.__globals__, 'get_col', lambda: SimpleNamespace(media=SimpleNamespace(dir=lambda: str(tmp_path))))
    return function


def test_media_readback_returns_exact_bytes_and_digest(real_mcp, monkeypatch, tmp_path):
    function = tool(real_mcp, monkeypatch, tmp_path)
    (tmp_path / 'synthetic.png').write_bytes(b'synthetic image bytes')
    result = function(filename='synthetic.png')
    assert result['filename'] == 'synthetic.png'
    assert base64.b64decode(result['data'], validate=True) == b'synthetic image bytes'
    assert result['size'] == 21
    assert result['sha256'] == hashlib.sha256(b'synthetic image bytes').hexdigest()


@pytest.mark.parametrize('filename', ['../synthetic.png', '/synthetic.png', 'a\\b.png', ' a.png', 'a.txt', 'a.png\0'])
def test_readback_rejects_unsafe_or_nonmedia_names(real_mcp, monkeypatch, tmp_path, filename):
    function = tool(real_mcp, monkeypatch, tmp_path)
    from anki_mcp_server.handler_wrappers import HandlerError
    with pytest.raises(HandlerError):
        function(filename=filename)


def test_readback_refuses_symlinks_and_oversized_media(real_mcp, monkeypatch, tmp_path):
    function = tool(real_mcp, monkeypatch, tmp_path)
    from anki_mcp_server.handler_wrappers import HandlerError
    original = tmp_path / 'real.png'
    original.write_bytes(b'abc')
    (tmp_path / 'alias.png').symlink_to(original)
    with pytest.raises(HandlerError):
        function(filename='alias.png')
    with original.open('wb') as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(HandlerError):
        function(filename='real.png')


def test_media_readback_is_discovered_as_read_only(tools_list):
    metadata = next(t for t in tools_list if t.name == 'read_media_file')
    assert metadata.annotations.readOnlyHint is True
    assert metadata.annotations.destructiveHint is False
