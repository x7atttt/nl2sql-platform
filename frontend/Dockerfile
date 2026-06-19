FROM node:22-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install --legacy-peer-deps

COPY . .
# 跳过 vue-tsc 类型检查（本地开发时已检查），直接 vite build
# 2核服务器 vue-tsc 要 4-5 分钟且长时间无输出，vite build 只要 1-2 分钟
RUN npx vite build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
