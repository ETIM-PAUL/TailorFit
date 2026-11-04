# TailorFit: one container serving the API, the landing page, the dashboard and the customer capture page.

# Node is only needed to decode SAM's masks (@meta-sam/parser); install it in its own stage.
FROM node:22-slim AS masks
WORKDIR /app/services/segmentation
COPY services/segmentation/package.json services/segmentation/package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=masks /usr/local/bin/node /usr/local/bin/node
WORKDIR /app

# Dependencies first, so code changes don't reinstall them
COPY services/api/requirements.txt services/api/
COPY services/measurement/requirements.txt services/measurement/
COPY services/segmentation/requirements.txt services/segmentation/
COPY services/quality-gate/requirements.txt services/quality-gate/
COPY services/confidence/requirements.txt services/confidence/
COPY services/style-preview/requirements.txt services/style-preview/
COPY services/fabric-calculator/requirements.txt services/fabric-calculator/
RUN for f in services/*/requirements.txt; do pip install -r "$f"; done

COPY . .
COPY --from=masks /app/services/segmentation/node_modules services/segmentation/node_modules

# Orders and kept photos live here; mount a persistent disk at /app/data to keep them across restarts.
RUN mkdir -p /app/data
WORKDIR /app/services/api
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
