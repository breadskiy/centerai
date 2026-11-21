FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CENTERAI_DATA=/workspace/data
WORKDIR /workspace
COPY backend/requirements.txt backend/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends libarchive13 && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir -r backend/requirements.txt && useradd -m centerai && mkdir data && chown centerai data
COPY backend/ backend/
COPY --from=frontend /build/dist frontend/dist
USER centerai
EXPOSE 8000
CMD ["python","-m","uvicorn","backend.api:app","--host","0.0.0.0","--port","8000"]
