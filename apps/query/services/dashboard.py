"""Dashboard BI 概览聚合服务。

按角色返回三类聚合数据：
1. trend — 最近 30 天查询趋势（按日聚合总查询数 + 成功数，ECharts 双线折线图用）
2. dataset_health — 数据集健康度（查询数/成功率/平均耗时/最后查询时间，前 10 名）
3. summary — 汇总卡片（总查询数/成功率/平均耗时/活跃数据集数）

权限分层对标 Power BI workspace 角色模型：
- admin → 全平台运营视角（所有 QueryHistory + 所有 Dataset）
- analyst/viewer → 个人视角（自己的 QueryHistory + 可见 Dataset）

数据集可见性复用 DatasetViewSet.get_queryset 三分支逻辑（admin 全量 /
analyst owner / viewer shares__shared_to），查询趋势按 user 过滤
（与 QueryHistoryView 一致）。
"""
import datetime
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.datasets.models import Dataset
from apps.query.models import QueryHistory

# USE_TZ=True：DB 存 UTC，TIME_ZONE='Asia/Shanghai' 仅影响模板渲染。
# 按日聚合必须显式传上海时区，否则按 UTC 切日（凌晨 0-8 点的查询会算到前一天）。
_SHANGHAI_TZ = ZoneInfo('Asia/Shanghai')
TREND_DAYS = 30


def _query_history_queryset(user) -> object:
    """按角色返回 QueryHistory queryset（trend 和 summary 共用）。"""
    if user.is_admin:
        return QueryHistory.objects.all()
    # analyst / viewer：只看自己的查询历史（与 QueryHistoryView 一致）
    return QueryHistory.objects.filter(user=user)


def _dataset_queryset(user) -> object:
    """按角色返回可见的 Dataset queryset（dataset_health 用）。

    口径与 DatasetViewSet.get_queryset / visibility.py 一致（对标 Tableau：
    所有权与角色解耦）——owner 永远可见 + 被分享给自己的。
    """
    from django.db.models import Q
    if user.is_admin:
        return Dataset.objects.all()
    # analyst/viewer 统一：owner=self 或被分享给自己的
    return Dataset.objects.filter(
        Q(owner=user) | Q(shares__shared_to=user)
    ).distinct()


def _build_trend(queryset) -> list[dict]:
    """最近 TREND_DAYS 天按日聚合查询数 + 成功数。

    前端需要连续日期（无查询的天补 0），这里只返回有数据的天，前端补齐。
    """
    start = timezone.now() - datetime.timedelta(days=TREND_DAYS - 1)
    rows = (
        queryset
        .filter(created_at__gte=start)
        .annotate(day=TruncDate('created_at', tzinfo=_SHANGHAI_TZ))
        .values('day')
        .annotate(
            count=Count('id'),
            success_count=Count('id', filter=Q(is_success=True)),
        )
        .order_by('day')
    )
    return [
        {'date': r['day'].isoformat(), 'count': r['count'], 'success_count': r['success_count']}
        for r in rows
    ]


def _build_dataset_health(dataset_qs) -> list[dict]:
    """数据集健康度：按查询数降序取前 10，附成功率/平均耗时/最后查询时间。

    success_rate 在 Python 层算（防 SQL 除零）。只显示有查询记录的数据集
    （query_count__gt=0），避免一堆 0 查询的数据集撑爆表格。
    """
    health = (
        dataset_qs
        .annotate(
            query_count=Count('queries'),
            success_count=Count('queries', filter=Q(queries__is_success=True)),
            avg_time_ms=Avg('queries__execution_time_ms'),
            last_query_at=Max('queries__created_at'),
        )
        .filter(query_count__gt=0)
        .order_by('-query_count')[:10]
    )
    result = []
    for d in health:
        # 除零保护：无查询已被 filter 挡住，但 double safety
        success_rate = (d.success_count / d.query_count) if d.query_count else 0
        result.append({
            'id': str(d.id),
            'name': d.name,
            'query_count': d.query_count,
            'success_rate': round(success_rate, 4),
            'avg_time_ms': round(d.avg_time_ms) if d.avg_time_ms else 0,
            'last_query_at': d.last_query_at.isoformat() if d.last_query_at else None,
        })
    return result


def _build_summary(query_qs, dataset_health: list[dict]) -> dict:
    """汇总卡片：总查询数/成功率/平均耗时/活跃数据集数。

    从 QueryHistory queryset 直接 aggregate，不依赖 trend（trend 只含 30 天）。
    """
    agg = query_qs.aggregate(
        total=Count('id'),
        success=Count('id', filter=Q(is_success=True)),
        avg_time=Avg('execution_time_ms'),
    )
    total = agg['total'] or 0
    success = agg['success'] or 0
    return {
        'total_queries': total,
        'success_rate': round(success / total, 4) if total else 0,
        'avg_time_ms': round(agg['avg_time']) if agg['avg_time'] else 0,
        'active_datasets': len(dataset_health),  # 有查询记录的数据集数
    }


def get_dashboard_stats(user) -> dict:
    """主入口：按角色返回 dashboard 全部聚合数据。"""
    query_qs = _query_history_queryset(user)
    dataset_qs = _dataset_queryset(user)
    trend = _build_trend(query_qs)
    dataset_health = _build_dataset_health(dataset_qs)
    summary = _build_summary(query_qs, dataset_health)
    return {
        'trend': trend,
        'dataset_health': dataset_health,
        'summary': summary,
    }
