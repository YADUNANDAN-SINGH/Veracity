# Veracity's hosted judge build: the dashboard and the API in one container.
# No phone and no models: calls are replayed scenarios run through the real scam
# rules, and Protected Send uses the real PayPal sandbox.
#
#   docker build -t veracity-judge .
#   docker run -p 8000:8000 --env-file veracity-backend/.env veracity-judge   → http://localhost:8000
#
# Render builds this file (render.yaml). The phone build runs natively on a Mac (README §6).

# ---- the dashboard, built once ----
FROM node:22-alpine AS web
WORKDIR /web
COPY veracity-frontend/veracity/package.json veracity-frontend/veracity/package-lock.json ./
RUN npm ci
COPY veracity-frontend/veracity/ ./
RUN npm run build

# ---- the API, which also serves the dashboard ----
FROM python:3.12-slim
WORKDIR /app
COPY veracity-backend/requirements-judge.txt ./
RUN pip install --no-cache-dir -r requirements-judge.txt
COPY veracity-backend/ ./
COPY --from=web /web/dist ./static
ENV VERA_MODE=judge \
    VERA_REGION=US \
    VERA_STATIC_DIR=/app/static \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
