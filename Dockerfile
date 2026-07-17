# Stage 1: build webui
FROM node:20-alpine AS webui-builder
WORKDIR /app/webui
COPY webui/package*.json ./
RUN npm ci
COPY webui/ .
RUN npm run build

# Stage 2: consolidated engine image - serves the FastAPI app AND every
# worker (experience/performance-trigger/telegram/paper-readiness/
# retraining). One image, one COPY of the whole source tree (respecting
# .dockerignore's exclusions - .venv/, node_modules/, data/, ml/,
# backtests/, etc., which arrive at runtime via compose volume mounts
# instead) rather than a hand-maintained per-worker COPY allow-list.
# This is the direct fix for development/Problems.md #1/#2/#20/#30 - four
# separate incidents where a per-worker Dockerfile's COPY list drifted out
# of sync with that worker's actual import graph and crash-looped on
# ModuleNotFoundError. With one image copying everything, that whole bug
# class is structurally impossible now. Each service's actual entrypoint
# is selected via docker-compose.yml's per-service `command:` override
# (CMD below is just the default/app entrypoint).
FROM python:3.11-slim
WORKDIR /app
COPY requirements/requirements.txt ./requirements/
RUN pip install --no-cache-dir -r requirements/requirements.txt
COPY . .
COPY --from=webui-builder /app/webui/dist ./webui/dist
EXPOSE 8000
CMD ["uvicorn", "monitoring.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
