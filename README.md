# AI 驱动的数据处理平台

Django + Celery + LangChain 构建的自然语言数据查询平台。分析师统一上传 CSV/Excel 维护共享数据源并按需分享，用户即可用自然语言提问，AI 自动生成 SQL 并执行返回结果，把分析师从重复取数中解放出来。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.1-green)](https://www.djangoproject.com/)
[![Vue](https://img.shields.io/badge/Vue-3.4-brightgreen)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 功能特性

- **数据集管理**：分析师上传 CSV/Excel 文件，异步解析入库，WebSocket 实时推送处理进度；支持批量上传（最多 10 个文件，单个串行处理）；三道规模上限保护（文件 50MB / 行数 10 万 / 列数 100）
- **自然语言查询**：AI 自动将中文问题转为 SQL 并执行（NL2SQL），7 步流水线（Schema 发现 → SQL 生成 → 安全校验 → 自动 LIMIT → 执行 → 失败重试 → 结果格式化）
- **Few-shot 语义检索**：基于 pgvector 把历史成功查询向量化，新问题按余弦相似度检索最相关的 3 条注入 Prompt（HNSW + cosine 索引），替代简单的时间倒序，提升 SQL 生成准确率
- **业务文档注入**：数据集支持填写业务说明/数据字典，独立段落注入 Prompt，帮助 LLM 理解字段业务语义（列统计告诉它"数据长什么样"，业务说明告诉它"数据是什么意思"）
- **智能推荐查询**：数据集处理完成后，LLM 根据 schema + 业务说明自动生成 4 条推荐查询（覆盖分布/排名/趋势/对比维度），缓解用户冷启动焦虑；异步生成不阻塞上传，结果缓存到 Dataset.suggested_questions
- **查询结果可视化**：规则引擎按列类型组合自动推荐图表（折线/柱状/饼图/散点/面积），支持手动切换类型与 X/Y 轴；LLM 智能图表推荐（基于问题语义 + SQL 语义 + 列统计，参考 LIDA Summary 模式）异步增强默认图，失败降级到规则引擎
- **数据分析**：自动统计每列类型、空值、分布、高频值等
- **查询历史**：持久化前 20 行结果预览，支持一键重跑历史 SQL 获取完整结果；SQL 列点击展开代码块（含复制）；按问题文本搜索（icontains，400ms 防抖）
- **数据导出**：查询结果导出为 CSV / Excel（viewer 也可导出，导出接口内部已重跑 SQL 取完整数据，无需前端先重跑）
- **RBAC 权限**：admin / analyst / viewer 三角色，通过 DatasetShare 分享模型实现数据集级授权，生产者/消费者职责分离；所有权与角色解耦（owner 永远可访问自己的数据，对标 Tableau），降级不丢数据访问权
- **分享管理**：分享记录独立页（侧边栏），按角色范围隔离（admin 看全平台 / analyst 看自己数据集的 / viewer 看分享给自己的），支持单条撤销；详情页对话框内可管理单数据集的分享对象
- **用户管理**：角色重分配 + 禁用/启用恢复（员工休假/返岗场景）
- **Dashboard BI 概览**：查询趋势 30 天折线图（ECharts）+ 数据集健康度表（查询数/成功率/平均耗时）+ 汇总卡片；分层视角（admin 全平台运营 / 普通用户个人面板），对标 Power BI workspace 角色模型
- **幂等上传**：Redis 分布式锁 + 数据库查重 + 数据库唯一约束，三道防线防重复；解析失败自动清理记录，避免永久阻塞重传
- **Celery 任务可靠性**：指数退避重试 + 死信队列，visibility_timeout 显式配置防 acks_late 重复执行
- **WebSocket 实时进度**：替代 HTTP 轮询，Celery 任务每处理 1 万行推送一次进度；连接鉴权（校验登录 + 数据集可见性）
- **NL2SQL 安全**：四层 SQL 安全校验（注释剥离 → SELECT 白名单 → 危险关键字词边界 → 分号注入拦截）
- **Schema 发现缓存**：复用 Redis 缓存 schema 摘要（TTL 7 天 + 主动失效），二次查询省 90%+ 计算成本

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| 后端 | Python 3.12, Django 5.1, DRF 3.14, Celery 5.3, Channels |
| 数据库 | PostgreSQL 15 + **pgvector**（few-shot 语义检索）, Redis 7 |
| AI/LLM | LangChain, 智谱 GLM (OpenAI 兼容 API), 智谱 embedding-3（1024 维） |
| 前端 | Vue 3.4, TypeScript, Element Plus 2.9, **ECharts 5**（查询结果可视化）, Pinia, Vue Router 4, Vite |
| 部署 | Docker Compose, Nginx, Daphne |

## 快速开始

### Docker Compose 部署

```bash
# 1. 克隆仓库
git clone https://github.com/x7atttt/nl2sql-platform.git
cd nl2sql-platform

# 2. 创建 .env.production 并填入真实值
cp .env.production.example .env.production
# 编辑：DJANGO_SECRET_KEY、DB_PASSWORD、LLM_API_KEY（DeepSeek）、EMBEDDING_API_KEY（智谱）、ALLOWED_HOSTS

# ⚠️ PostgreSQL 需 pgvector 扩展（few-shot 语义检索依赖）
#    docker-compose.yml 已用 pgvector/pgvector:pg15 镜像（预装 vector 扩展二进制），
#    migrate 时会自动 CREATE EXTENSION vector（迁移内置 RunSQL，幂等）

# 3. 构建并启动（首次会构建镜像，约 5-10 分钟）
docker compose --env-file .env.production up -d --build

# 4. 创建管理员账号
docker compose exec -it django python manage.py createsuperuser

# 5. 设置管理员角色
docker compose exec django python manage.py shell -c "
from apps.users.models import User
u = User.objects.first()
u.role = 'admin'
u.save()
"

# 6. 访问 http://你的服务器IP（本地部署则访问 http://localhost）
```

> 2核2G 服务器构建可能 OOM，建议先加 swap：`sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

### 本地开发

> ⚠️ 后端**必须**用 `daphne` 启动（不能用 `runserver`），因为 `runserver` 是 WSGI，不支持 WebSocket。

```bash
# 后端（HTTP + WebSocket，必须用 daphne）
pip install -r requirements.txt
python manage.py migrate
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Celery（Windows 必须用 --pool=solo，prefork 不支持）
celery -A config worker -l info --pool=solo
celery -A config beat -l info

# 前端
cd frontend
pnpm install
pnpm run dev    # http://localhost:5173
```

> ⚠️ **必须同时启动 3 个终端**：daphne（HTTP + WS）+ celery worker（异步任务）+ vite dev（前端）。少起任何一个都会导致功能异常。

> ⚠️ **必须同时启动 3 个终端**：daphne（HTTP + WS）+ celery worker（异步任务）+ vite dev（前端）。少起任何一个都会导致功能异常。

## 架构图

```
                    ┌─────────────┐
                    │   Nginx     │ :80
                    │  (前端)      │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │ /          │ /api/*     │ /ws/*
              ▼            ▼            ▼
        Vue3 SPA     ┌─────────────────────┐
        (dist)       │  Django (Daphne)    │ :8000
                      │  DRF + Channels     │
                      └──┬──────┬──────┬───┘
                         │      │      │
                    ┌────▼┐ ┌──▼──┐ ┌─▼──────┐
                    │ PG  │ │Redis│ │ Celery  │
                    │ :5432│ │:6379│ │ Worker  │
                    └─────┘ └─────┘ │ + Beat  │
                                     └─────────┘
```

## 项目结构

```
├── config/                  # Django 配置、URL、Celery、ASGI
├── apps/
│   ├── users/               # 用户模型、RBAC、认证 API
│   ├── datasets/            # 上传、解析、Celery 任务、分析器、可见性隔离
│   ├── query/               # NL2SQL 服务、查询 API、Dashboard BI
│   └── export/              # CSV/Excel 导出
├── frontend/                # Vue 3 + TypeScript + Element Plus
│   ├── src/views/           # 页面（Dashboard/数据集列表/详情/查询历史/分享记录/用户管理）
│   ├── src/styles/          # CSS 主题系统
│   ├── src/components/      # 公共组件（图表/滑块验证码/布局）
│   └── Dockerfile           # 多阶段构建（pnpm build → Nginx）
├── nginx/
│   └── nginx.conf           # 反向代理配置（含 WebSocket + 大文件上传）
├── .github/workflows/       # GitHub Actions（构建镜像推阿里云 ACR）
├── docker-compose.yml       # 6 个服务（django/celery-worker/celery-beat/nginx/db/redis）
├── .env.production.example  # 环境变量模板（占位符，复现用）
├── Dockerfile               # 后端镜像（BuildKit cache + collectstatic 构建期）
└── requirements.txt         # Python 依赖
```

## API 接口概览

| 接口 | 方法 | 描述 | 权限 |
|------|------|------|------|
| `/api/users/register/` | POST | 注册 | 公开 |
| `/api/users/login/` | POST | 登录 | 公开 |
| `/api/users/logout/` | POST | 注销 | 需登录 |
| `/api/users/profile/` | GET | 当前用户信息 | 需登录 |
| `/api/users/manage/` | GET | 用户列表 | 管理员 |
| `/api/users/manage/{id}/` | PATCH/DELETE | 改角色 / 禁用 | 管理员 |
| `/api/datasets/` | GET/POST | 列表 / 上传（支持批量） | 上传：Analyst+ |
| `/api/datasets/{id}/` | GET/PATCH/DELETE | 详情 / 改业务说明 / 删除 | 改/删：Analyst+ |
| `/api/datasets/{id}/analysis/` | GET | 列统计 | 需登录 |
| `/api/datasets/{id}/share/` | POST | 分享数据集给指定用户 | Analyst+ |
| `/api/datasets/{id}/shares/` | GET | 查看某数据集的分享记录 | Analyst+ |
| `/api/datasets/{id}/shares/{share_id}/` | DELETE | 撤销单条分享 | Analyst+ |
| `/api/datasets/shares_list/` | GET | 全局分享记录列表（侧边栏页） | 需登录 |
| `/api/datasets/shareable_users/` | GET | 可分享的用户列表 | Analyst+ |
| `/api/query/{dataset_id}/` | POST | 自然语言查询 | 需登录 |
| `/api/query/stats/` | GET | Dashboard BI 聚合数据 | 需登录 |
| `/api/query/history/` | GET | 查询历史（含前 20 行预览，支持 ?search= 和 ?dataset_id=） | 需登录 |
| `/api/query/history/{id}/rerun/` | POST | 重跑历史 SQL 取完整结果 | 需登录 |
| `/api/query/{query_id}/chart-suggest/` | POST | LLM 智能图表推荐 | 需登录 |
| `/api/export/{query_id}/csv/` | GET | 导出 CSV | 需登录 |
| `/api/export/{query_id}/xlsx/` | GET | 导出 Excel | 需登录 |

### WebSocket 接口

| 接口 | 描述 | 认证 |
|------|------|------|
| `/ws/datasets/{dataset_id}/progress/` | 数据集处理进度实时推送 | Session（Cookie） |

**消息格式**（服务端 → 客户端，JSON）：

```json
{
  "progress": 30000,
  "status": "processing",
  "message": "已处理 30000 行"
}
```

`status` 取值：`processing`（处理中）| `completed`（完成）| `failed`（失败，终态后客户端主动关闭连接）

## RBAC 权限矩阵

通过 DatasetShare 分享模型实现数据集级授权：分析师上传后主动分享给指定用户，viewer 仅能查询被分享的数据集，实现生产者/消费者职责分离。

| 功能 | Admin | Analyst | Viewer |
|------|:-----:|:-------:|:------:|
| 上传数据集 | ✅ 全部 | ✅ 自己的 | ❌ |
| 删除数据集 | ✅ 全部 | ✅ 自己的 | ❌ |
| 分享数据集 | ✅ | ✅ 自己的 | ❌ |
| 撤销分享 | ✅ 任意 | ✅ 自己 owner 的 | ❌ |
| 可见数据集 | ✅ 全部 | ✅ owner + 被分享的 | ✅ owner + 被分享的 |
| 查询（NL2SQL） | ✅ 全部 | ✅ owner + 被分享的 | ✅ owner + 被分享的 |
| 查询历史 / 重跑 | ✅ 自己的 | ✅ 自己的 | ✅ 自己的 |
| 导出数据 | ✅ | ✅ 自己的 | ✅ 自己的 |
| 管理用户 | ✅ | ❌ | ❌ |

数据可见性统一口径（`apps/datasets/services/visibility.py`）：admin 看全部，analyst/viewer 看 owner=self 或被分享给自己的。**所有权与角色解耦**——owner 永远能访问自己的数据（无论当前角色），对标 Tableau：角色决定"能做什么操作"，所有权决定"拥有什么资源"，降级不丢数据访问权。撤销分享后历史 QueryHistory 仍存在，但 rerun/export/chart 接口实时复检可见性，不可见返回 403。

## 参考项目

本项目在算法层和产品形态上借鉴了以下开源项目（代码独立实现，未直接复制）：

- **[vanna-ai/vanna](https://github.com/vanna-ai/vanna)**（20K+ stars）— NL2SQL 框架，本项目借鉴：
  - RAG for few-shot retrieval 的设计理念（pgvector 语义检索替代时间倒序）
  - 图表推荐的三要素（question + sql + df 元数据）
- **[microsoft/LIDA](https://github.com/microsoft/LIDA)** — 自动化数据可视化，本项目借鉴：
  - Summary 模式（chart_advisor 的 `_build_column_stats` 统计摘要思路：只给 LLM 看列类型 + distinct 数 + 样本值，不塞全量数据）
  - `clean_code_snippet` 的正则思路（`_extract_json` 防止 LLM 输出被 markdown 包裹）
- **[Apache Superset](https://superset.apache.org/)** / **[Tableau](https://www.tableau.com/)** — BI 平台，本项目借鉴：
  - 三级角色模型（admin/analyst/viewer 对应 Superset Admin/Alpha/Viewer，Tableau Site Administrator/Explorer/Viewer）
  - 数据集级授权机制（DatasetShare 对应 Superset dashboard owners、Tableau workbook 权限）
  - 所有权与角色解耦原则（owner 永远可访问自己的数据，对标 Tableau Change Owner）
- **[Django 官方文档](https://docs.djangoproject.com/)** / **[DRF 文档](https://www.django-rest-framework.org/)** — 工程实现参考

> 本项目工程层（RBAC / 幂等 / 异步 / WebSocket / 可见性隔离）比 Vanna 完整，算法层（few-shot 语义检索 / LLM 图表推荐 / 智能推荐查询）借鉴 LIDA + Vanna 的设计思路但独立实现。

## 环境变量

复制 `.env.production.example` 为 `.env.production`，填入真实值（`.env.production` 已 gitignore，不会泄露密钥）。

| 变量 | 必填 | 说明 |
|------|:----:|------|
| `DJANGO_SECRET_KEY` | 是 | 随机密钥，用 `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` 生成 |
| `DJANGO_DEBUG` | 是 | 生产环境填 `False` |
| `DB_HOST` | 是 | `db`（Docker）/ `localhost`（本地） |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | 是 | PostgreSQL 凭证 |
| `REDIS_URL` | 是 | `redis://redis:6379/1`（Docker） |
| `LLM_API_KEY` | 是 | **DeepSeek API Key**（NL2SQL 生成 SQL + 图表推荐 + 推荐查询），[获取](https://platform.deepseek.com/api_keys) |
| `LLM_API_BASE` | 是 | `https://api.deepseek.com` |
| `LLM_MODEL` | 否 | 默认 `deepseek-chat` |
| `EMBEDDING_API_KEY` | 是 | **智谱 API Key**（few-shot 语义检索的问题向量化，embedding-3 1024 维），[获取](https://open.bigmodel.cn/usercenter/apikeys) |
| `EMBEDDING_API_BASE` | 是 | `https://open.bigmodel.cn/api/paas/v4`（智谱 OpenAI 兼容协议） |
| `ALLOWED_HOSTS` | 是 | 逗号分隔的域名/IP 列表 |

> **为什么 LLM 和 Embedding 用两个供应商？** DeepSeek 性价比高（NL2SQL 主链路），但不提供 embedding 接口；智谱 embedding-3（1024 维）用于 few-shot 语义检索。两个服务独立配置，互不干扰——这也是工程上的解耦，未来换任一供应商都不影响另一条链路。

## License

MIT
