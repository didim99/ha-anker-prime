# Test image: a Python base image plus one requirements file (see compose.yaml).
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ARG REQUIREMENTS=
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir 'uv~=0.9'
COPY requirements-test-*.txt /tmp/requirements/
RUN if [ -n "$REQUIREMENTS" ]; then \
        uv pip install --system --no-cache -r "/tmp/requirements/$REQUIREMENTS"; \
    fi

ENTRYPOINT ["sh", "/src/ha-anker-prime/docker/run-tests.sh"]
