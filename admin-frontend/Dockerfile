FROM node:22-slim AS build

WORKDIR /app

# 独立 admin 前端复用 student frontend 的 Admin 页面与 auth/request 客户端
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
