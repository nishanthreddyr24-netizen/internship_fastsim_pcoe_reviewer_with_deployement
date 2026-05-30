FROM python:3.11-slim AS fastsim-builder

ENV CARGO_HOME=/cargo \
    RUSTUP_HOME=/rustup

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libssl-dev patchelf pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal

ENV PATH="/cargo/bin:${PATH}"

RUN pip install --no-cache-dir "maturin>=1.8"

COPY pyproject.toml Cargo.toml Cargo.lock MANIFEST.in LICENSE.md README.md ./
COPY fastsim-core ./fastsim-core
COPY fastsim-py ./fastsim-py
COPY fastsim-cli ./fastsim-cli
COPY cal_and_val ./cal_and_val
COPY python ./python

RUN maturin build --release --manifest-path fastsim-py/Cargo.toml --out /wheels

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=fastsim-builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -f /tmp/*.whl

COPY app ./app
COPY vehicles_enrichment_GLOBAL_20260517_0915.csv .
COPY india_ev_reviews.xlsx .
COPY normalized_new_delhi_chargers.csv .
COPY route_edges.json .
COPY route_edges_charger.json .
COPY valhalla.json .

RUN useradd --create-home --shell /usr/sbin/nologin fastsim \
    && chown -R fastsim:fastsim /app

USER fastsim
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "gunicorn app.main:app -w ${WEB_CONCURRENCY:-2} -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile -"]
