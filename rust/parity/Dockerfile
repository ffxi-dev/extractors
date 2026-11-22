# The parity image: the package, its Rust extractors built in. ./parity builds it on lsb.
# Trixie for gcc 14, which xicap's C++23 needs; its python3 is 3.13.
FROM rust:1-trixie
RUN apt-get update -q && apt-get install -y -q --no-install-recommends cmake libzstd-dev pkg-config python3 \
    python3-dev && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
# The package with extractors_rs, built as a wheel; Cargo's downloads and builds, xicap's clone among them,
# kept between runs.
ENV CARGO_TARGET_DIR=/cargo/target
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/cargo/target \
    uv sync --frozen --no-dev --no-editable
