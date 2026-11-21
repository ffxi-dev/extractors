# What CI checks: ruff, mypy, the tests with every pin, and indexing the fixtures, against the ClickHouse
# compose.yaml runs. `docker build .`
FROM python:3.13-slim
RUN apt-get update -q && apt-get install -y -q --no-install-recommends build-essential cmake libzstd-dev \
    pkg-config git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
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
