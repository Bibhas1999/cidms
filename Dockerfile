# Supreme DMS: one image serving the API and the built Svelte app.
#   docker build -t supreme-dms .
#   docker run --env-file .env -p 8000:8000 supreme-dms
# Migrations run as a separate step before the new image takes traffic:
#   docker run --env-file .env supreme-dms python -m alembic upgrade head

FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY migrations/ migrations/
COPY alembic.ini .
COPY --from=web /web/dist web/dist
RUN useradd --create-home --uid 10001 sdms
USER sdms
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
