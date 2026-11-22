# What CI checks: ruff, mypy, the tests with every pin, and indexing the fixtures, against the ClickHouse
# compose.yaml runs; and the Rust extractors: rustfmt, clippy, cargo test, and extractors_rs's wheel against
# the same pins. `docker build .`
FROM python:3.13-slim
RUN apt-get update -q && apt-get install -y -q --no-install-recommends build-essential cmake libzstd-dev \
    pkg-config git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
# Rust, and xicap's source at the tag pyproject.toml pins, which xc-core compiles its reader from (gcc 14).
COPY --from=rust:1.100-slim-trixie /usr/local/rustup /usr/local/rustup
COPY --from=rust:1.100-slim-trixie /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo XICAP_SRC=/opt/xicap
RUN /usr/local/cargo/bin/rustup component add clippy rustfmt \
    && git clone -q --depth 1 --branch v7.2.0 https://github.com/ffxi-dev/xicap /opt/xicap
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never \
    PATH=/opt/venv/bin:/usr/local/cargo/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY --from=clickhouse/clickhouse-server:26.8.36.3 /usr/bin/clickhouse /usr/bin/clickhouse
COPY --from=clickhouse/clickhouse-server:26.8.36.3 /etc/clickhouse-server /etc/clickhouse-server
COPY clickhouse/config.xml /etc/clickhouse-server/config.d/ffxi.xml
COPY clickhouse/users.xml /etc/clickhouse-server/users.d/ffxi.xml
COPY . .
RUN uv sync --frozen
# The cache mounts keep crates and builds between runs on the same host; the wheel leaves the mount.
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/app/target \
    cargo fmt --check && cargo clippy --workspace --tests -- -D warnings && cargo test --workspace \
    && uv tool run maturin@1.16.0 build --release --auditwheel skip -m rust/xc-py/Cargo.toml -i /opt/venv/bin/python -o /tmp/wheels \
    && uv pip install --python /opt/venv/bin/python /tmp/wheels/*.whl
RUN ruff check . && ruff format --check . && mypy \
    && (clickhouse server -C /etc/clickhouse-server/config.xml > /tmp/clickhouse.log 2>&1 &) \
    && for i in $(seq 60); do clickhouse client --user ffxi --password ffxi -q 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done \
    && pytest -q -p no:cacheprovider tests rust/xc-py/tests \
    && ffxi-extractors index --no-names tests/data/memoria.xicap tests/data/captain.xicap \
    && test "$(clickhouse client --user ffxi --password ffxi -d ffxi -q 'SELECT count() > 0 FROM bestiary_fights')" = 1
