FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libegl1 libfontconfig1 libxkbcommon0 libdbus-1-3 libatomic1 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxrandr2 libxtst6 libxi6 libasound2 libxkbfile1 libgssapi-krb5-2 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'aqt==26.9.2' 'typing-extensions==4.16.0' pytest pytest-asyncio
ARG SOURCE_REVISION=uncommitted-dirty
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
COPY anki_mcp_server.ankiaddon /artifact/addon.ankiaddon
COPY tests/smoke/import_smoke.py /artifact/import_smoke.py
COPY tests/isolated/synthetic_collection.py /artifact/synthetic_collection.py
RUN python -m zipfile -e /artifact/addon.ankiaddon /artifact/addon
RUN chmod -R a+rX /artifact && python -c "import pathlib, subprocess, sys; p=next(pathlib.Path('/artifact/addon/vendor/shared').glob('pydantic-*.dist-info')); subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pydantic=='+p.name[len('pydantic-'):-len('.dist-info')]])"
RUN useradd -u 1000 -M tester
ENV QT_QPA_PLATFORM=offscreen HOME=/tmp/test-home
USER 1000:1000
CMD ["python", "/artifact/import_smoke.py", "--preload-aqt", "/artifact/addon"]
