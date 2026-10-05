# Build context is the REPOSITORY ROOT (see docker-compose.yml): docker build -f frontend/Dockerfile .
# Builds the SPA, then serves it from an unprivileged nginx that is also the TLS edge (deploy/nginx/nginx.conf).
FROM node:22-slim AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
RUN npx vite build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/proxy_params /etc/nginx/proxy_params
EXPOSE 8080 8443
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD nc -z 127.0.0.1 8443 || exit 1
