FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
RUN npm ci
COPY frontend frontend
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    BIM_FRONTEND_DIR=/app/frontend/dist \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/requirements.lock backend/requirements.lock
COPY backend/app backend/app
RUN pip install --no-cache-dir -c backend/requirements.lock ./backend
COPY --from=frontend /build/frontend/dist frontend/dist
EXPOSE 10000
CMD ["python", "-m", "app.web"]
