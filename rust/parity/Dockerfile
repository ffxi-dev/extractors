# The parity image: the Python extractors, and the Rust ones once rust/ builds them. ./parity builds it on lsb.
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
RUN uv sync --frozen --no-dev
# xicap's source at the tag pyproject.toml pins, which xc-core's build.rs compiles the reader from.
RUN git clone -q --depth 1 -b v7.2.0 https://github.com/ffxi-dev/xicap /xicap
# Each maturin crate under rust/ into the same environment, Cargo's downloads and builds kept between runs.
ENV CARGO_TARGET_DIR=/cargo/target XICAP_SRC=/xicap
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/cargo/target \
    for p in rust/*/pyproject.toml; do [ ! -f "$p" ] || uv pip install --python /opt/venv/bin/python \
    "$(dirname "$p")"; done
