FROM node:22-slim AS build

WORKDIR /app

# 共享的 Admin 页面在 frontend/src 下，需要 frontend 的 node_modules 才能解析 React/antd
COPY frontend/package.json frontend/package-lock.json ./frontend/
WORKDIR /app/frontend
RUN npm ci

WORKDIR /app
COPY admin-frontend/package.json admin-frontend/package-lock.json ./admin-frontend/
WORKDIR /app/admin-frontend
RUN npm ci

COPY admin-frontend ./
COPY frontend/src /app/frontend/src

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/admin-frontend/dist /usr/share/nginx/html
COPY admin-frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
