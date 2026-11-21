# What CI checks: ruff, the tests with every pin, and indexing the fixtures, against the ClickHouse
# compose.yaml runs. `docker build .`; while packets is private, add --secret id=packets_key,src=<deploy key>.
FROM python:3.13-slim
RUN apt-get update -q && apt-get install -y -q --no-install-recommends build-essential cmake libzstd-dev \
    pkg-config git openssh-client && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
# The key is a build secret, so no layer keeps it.
RUN --mount=type=secret,id=packets_key \
    if [ -s /run/secrets/packets_key ]; then \
      mkdir -p /root/.ssh && install -m 600 /run/secrets/packets_key /root/.ssh/packets \
      && printf 'Host github.com\n  IdentityFile /root/.ssh/packets\n  IdentitiesOnly yes\n' > /root/.ssh/config \
      && git config --global url."git@github.com:ffxi-dev/packets".insteadOf "https://github.com/ffxi-dev/packets" \
      && ssh-keyscan github.com > /root/.ssh/known_hosts 2>/dev/null; \
    fi \
    && uv sync --frozen --no-install-project \
    && rm -rf /root/.ssh /root/.gitconfig
COPY --from=clickhouse/clickhouse-server:26.8.36.3 /usr/bin/clickhouse /usr/bin/clickhouse
COPY --from=clickhouse/clickhouse-server:26.8.36.3 /etc/clickhouse-server /etc/clickhouse-server
COPY clickhouse/config.xml /etc/clickhouse-server/config.d/ffxi.xml
COPY clickhouse/users.xml /etc/clickhouse-server/users.d/ffxi.xml
COPY . .
RUN uv sync --frozen
RUN ruff check . && ruff format --check . && mypy \
    && (clickhouse server -C /etc/clickhouse-server/config.xml > /tmp/clickhouse.log 2>&1 &) \
    && for i in $(seq 60); do clickhouse client --user ffxi --password ffxi -q 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done \
    && pytest -q -p no:cacheprovider \
    && ffxi-extractors index --no-names tests/data/memoria.xicap tests/data/captain.xicap \
    && test "$(clickhouse client --user ffxi --password ffxi -d ffxi -q 'SELECT count() > 0 FROM bestiary_fights')" = 1
