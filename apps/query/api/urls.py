from django.urls import path
from . import views

urlpatterns = [
    # Dashboard BI 概览（放在 uuid 路由前，避免被 <uuid:dataset_id> 误匹配）
    path('stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    # 多数据集联合查询（同样放在 uuid 路由前）
    path('multi/', views.NL2SQLMultiQueryView.as_view(), name='nl2sql-multi-query'),
    path('history/', views.QueryHistoryView.as_view(), name='query-history'),
    path('history/<uuid:history_id>/rerun/', views.QueryRerunView.as_view(), name='query-rerun'),
    path('<uuid:query_id>/chart-suggest/', views.ChartSuggestView.as_view(), name='chart-suggest'),
    path('<uuid:dataset_id>/', views.NL2SQLQueryView.as_view(), name='nl2sql-query'),
]
