# Test image: a Python base image plus one requirements file (see compose.yaml).
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ARG REQUIREMENTS=
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# A C compiler for dependencies without wheels for the image's Python, e.g.
# lru-dict 1.3.0 (Home Assistant 2026.1) on Python 3.13.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'uv~=0.9'
COPY requirements-test-*.txt /tmp/requirements/
RUN if [ -n "$REQUIREMENTS" ]; then \
        uv pip install --system --no-cache -r "/tmp/requirements/$REQUIREMENTS"; \
    fi

ENTRYPOINT ["sh", "/src/ha-anker-prime/docker/run-tests.sh"]
