# syntax=docker/dockerfile:1

# --- build stage: resolve and install the locked dependencies with uv -------------------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# The package version comes from the Git tag; there is no .git in the build context,
# so the release workflow passes it in (see publish.yml).
ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# --- runtime stage: no uv, no build tools -----------------------------------------------
FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# ssh refuses to run for a uid that has no passwd entry, so the runtime user is a real one
# with a fixed uid. Own the notes directory and the deploy key with uid 10001 on the host.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin notes

COPY --from=builder /opt/venv /opt/venv
COPY known_hosts /app/known_hosts

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    NOTES_DIR=/data/notes \
    NOTES_KNOWN_HOSTS=/app/known_hosts

# The commit this image was built from (the release workflow passes it); shown by /version.
ARG GIT_COMMIT=unknown
ENV NOTES_MANAGER_COMMIT=${GIT_COMMIT}

USER notes
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read() == b'ok' else 1)"]

# tini is process 1: it collects the processes that git or ssh leave orphaned, which would
# otherwise pile up as zombies until the container hits its process limit.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["notes-manager"]
