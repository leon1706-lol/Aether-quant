# Stage 1: build webui
FROM node:20-alpine AS webui-builder
WORKDIR /app/webui
COPY webui/package*.json ./
RUN npm ci
COPY webui/ .
RUN npm run build

# Stage 2: Python runtime (FastAPI server only — no ML deps)
FROM python:3.11-slim
WORKDIR /app
COPY requirements/requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY monitoring/ ./monitoring/
COPY visualization/ ./visualization/
COPY --from=webui-builder /app/webui/dist ./webui/dist
EXPOSE 8000
CMD ["uvicorn", "monitoring.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
