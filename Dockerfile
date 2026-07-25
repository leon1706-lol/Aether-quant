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

# Optional C++/pybind11 accelerator for inference/exported_model.py's
# _linear_batched() (development/Problems.md #32). This was previously
# never built for the actual container image - only ever built manually
# on a developer's own host machine for that machine's own (ABI-
# incompatible) local Python version, so the compiled .pyd/.so it produced
# never reached any deployed image. python:3.11-slim ships no C++
# compiler, so build-essential is installed just for this step and purged
# again in the SAME RUN (a separate `apt-get purge` in a later RUN would
# not shrink the image - Docker layers are additive). The whole extension
# is optional by design (inference/exported_model.py deferred-imports it
# and falls back to a pure-NumPy path on ANY import/call failure), so
# this step is deliberately soft-fail: if anything here breaks (a future
# base-image change, a pybind11/ABI mismatch, etc.) the `|| echo` swallows
# it and the Docker build still succeeds, exactly like every environment
# that has never had the accelerator built.
RUN (apt-get update && \
        apt-get install -y --no-install-recommends build-essential && \
        pip install --no-cache-dir "pybind11>=2.10" && \
        pip install --no-cache-dir ./cpp_inference_ext && \
        apt-get purge -y --auto-remove build-essential && \
        rm -rf /var/lib/apt/lists/*) \
    || echo "cpp_inference_ext: optional C++ accelerator build failed or was skipped - continuing without it (see development/Problems.md #32/#68)"

COPY --from=webui-builder /app/webui/dist ./webui/dist
EXPOSE 8000
CMD ["uvicorn", "monitoring.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
