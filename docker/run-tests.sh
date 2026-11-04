#!/bin/sh
# Runs the checks inside a test container (see compose.yaml).
#
#   run-tests.sh integration [pytest args]  ruff, mypy, pytest of this repo
#   run-tests.sh library [pytest args]      ruff, mypy, pytest of the library
#
# Set MYPY=0 to skip mypy in integration mode (see compose.yaml).
#
# Both repositories are mounted read-only. The library is installed from a
# fresh copy of its working tree on every run, so changes show up at once and
# no build files land in the mounted folders.
set -eu

HA_REPO=${HA_REPO:-/src/ha-anker-prime}
LIBRARY_REPO=${LIBRARY_REPO:-/src/anker-prime-driver}
MODE=${1:-integration}
if [ $# -gt 0 ]; then
    shift
fi

export PYTHONDONTWRITEBYTECODE=1
export RUFF_CACHE_DIR=/tmp/ruff-cache
export MYPY_CACHE_DIR=/tmp/mypy-cache
PYTHON=$(command -v python)
LIBRARY_COPY=/tmp/anker-prime-driver

copy_library() {
    rm -rf "$LIBRARY_COPY"
    mkdir -p "$LIBRARY_COPY"
    tar -C "$LIBRARY_REPO" --exclude=.git --exclude=.venv --exclude=venv \
        --exclude=build --exclude=dist --exclude='*.egg-info' \
        --exclude=__pycache__ --exclude='.*_cache' -cf - . \
        | tar -C "$LIBRARY_COPY" -xf -
}

case "$MODE" in
    integration)
        copy_library
        uv pip install --quiet --python "$PYTHON" "$LIBRARY_COPY"
        "$PYTHON" "$HA_REPO/docker/versions.py"
        cd "$HA_REPO"
        ruff check
        if [ "${MYPY:-1}" != 0 ]; then
            mypy
        fi
        "$PYTHON" -m pytest "$@"
        ;;
    library)
        copy_library
        uv pip install --quiet --python "$PYTHON" \
            -r "$LIBRARY_COPY/requirements-dev.txt" "$LIBRARY_COPY"
        echo "Python $("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"
        cd "$LIBRARY_REPO"
        ruff check
        mypy
        "$PYTHON" -m pytest -W error -p no:cacheprovider "$@"
        ;;
    *)
        echo "unknown mode: $MODE (expected integration or library)" >&2
        exit 2
        ;;
esac
