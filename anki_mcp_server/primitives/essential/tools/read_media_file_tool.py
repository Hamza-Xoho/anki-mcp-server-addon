"""Bounded byte readback confined to the active collection's media directory."""
import base64
import hashlib
import os
from pathlib import Path
import stat
from typing import Annotated, Any

from pydantic import Field

from ....tool_decorator import Tool
from ....handler_wrappers import HandlerError, get_col
from ....media_validators import sanitize_media_filename, validate_media_file_path, validate_media_filename_type

_MAX_BYTES = 8 * 1024 * 1024


@Tool(
    'read_media_file',
    'Read one exact media filename from the active collection, returning base64 bytes, '
    'size and SHA-256 for content verification. Refuses paths, symbolic links, '
    'non-media files and files over 8 MiB; never truncates successful responses.',
    title='Read Media File',
)
def read_media_file(filename: Annotated[str, Field(description='Exact media filename, not a path or URL')]) -> dict[str, Any]:
    if sanitize_media_filename(filename) != filename:
        raise HandlerError('Use an exact media filename, not a path', code='validation_error')
    validate_media_filename_type(filename)
    directory = Path(get_col().media.dir())
    path = directory / filename
    if path.is_symlink():
        raise HandlerError('Media readback does not follow symbolic links', code='validation_error')
    resolved = validate_media_file_path(str(path), import_dir=str(directory))
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(resolved, flags)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES:
                raise HandlerError('Media must be a regular file no larger than 8 MiB', code='limit_exceeded')
            data = stream.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise HandlerError('Media exceeds the 8 MiB readback limit', code='limit_exceeded')
    except OSError as exc:
        raise HandlerError('Media file is missing or unreadable', code='not_found') from exc
    return {'filename': filename, 'data': base64.b64encode(data).decode('ascii'),
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
