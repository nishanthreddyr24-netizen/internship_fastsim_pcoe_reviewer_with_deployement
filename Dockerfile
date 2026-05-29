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

COPY app ./app
COPY python ./python
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
