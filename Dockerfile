# syntax=docker/dockerfile:1.7
# 启用 BuildKit，支持 --mount=type=cache 持久化 pip 下载缓存

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 系统依赖：libpq-dev 给 psycopg2-binary 运行时用（slim 镜像无）
# gcc 已不再需要（--only-binary 强制 wheel 不编译），但保留以防个别包无 wheel 回退
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# --only-binary=:all: 强制使用预编译 wheel，跳过 C 扩展编译（pandas/numpy/cryptography 等）
# 实测在 2核服务器上 pip install 从 5+ 分钟降至 1 分钟内
# --mount=type=cache 持久化 pip 下载缓存，二次构建复用（CI 和本地都受益）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

# collectstatic 在构建期执行一次（不在每次启动跑）
# collectstatic 不需要 DB 连接，但需要 Django settings 能加载（提供占位 SECRET_KEY 避免 crash）
RUN DJANGO_SECRET_KEY=build-placeholder DJANGO_DEBUG=False \
    DB_HOST= DB_NAME= DB_USER= DB_PASSWORD= REDIS_URL= \
    LLM_API_KEY= EMBEDDING_API_KEY= ALLOWED_HOSTS= \
    python manage.py collectstatic --noinput

EXPOSE 8000

# CMD 用 daphne（与 docker-compose 一致；移除被覆盖的 gunicorn）
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
