# Veracity dashboard: multi-stage image.
#
#   dev    Vite dev server with hot reload (mount ./src as a volume)
#   build  compiles the static bundle
#   prod   (default) nginx serves the bundle and proxies /api and /ws to FastAPI
#
# docker build -t veracity-frontend .                # prod
# docker build --target dev -t veracity-frontend-dev .

# ---- deps: install node_modules once, shared by dev and build ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: hot-reload server on :5173 ----
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- build: static files in /app/dist ----
FROM deps AS build
COPY . .
RUN npm run build

# ---- prod: nginx on :80 ----
FROM nginx:1.27-alpine AS prod
# The nginx image runs envsubst on /etc/nginx/templates/*.template at start-up,
# so BACKEND_URL can be changed without rebuilding the image.
ENV BACKEND_URL=http://backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
