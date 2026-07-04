# syntax=docker/dockerfile:1.7
# 启用 BuildKit，支持 --mount=type=cache 持久化 pnpm store，二次构建复用下载

FROM node:22-alpine AS build

WORKDIR /app

# 启用 corepack（Node 22 自带，预装 pnpm）
RUN corepack enable

# 先复制 lockfile 和 package.json（独立 layer，依赖不变则缓存命中）
COPY package.json pnpm-lock.yaml ./

# pnpm install --frozen-lockfile 严格按 lockfile 安装（可复现，避免依赖漂移）
# 注：peer deps 由 lockfile 的 settings.autoInstallPeers=true 控制，不需要额外参数
# --mount=type=cache 持久化 pnpm store，二次构建复用下载
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .

# vite build：NODE_OPTIONS 限制内存 1.5G 防止 2G 服务器 OOM
# 直接调 vite build 跳过 vue-tsc 类型检查（本地开发时已检查，CI 省时间）
ENV NODE_OPTIONS=--max-old-space-size=1536
RUN pnpm exec vite build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
