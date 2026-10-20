from django.urls import path
from . import views
from . import chat_views

urlpatterns = [
    # 对话（SSE 流式问答）
    path('chat/conversations/', chat_views.ChatConversationView.as_view(), name='chat-conversations'),
    path('chat/conversations/<uuid:conv_id>/', chat_views.ChatConversationDetailView.as_view(), name='chat-conversation-detail'),
    path('chat/conversations/<uuid:conv_id>/messages/', chat_views.ChatMessageStreamView.as_view(), name='chat-messages'),
    path('chat/messages/<int:message_id>/trace/', chat_views.ChatTraceView.as_view(), name='chat-trace'),
    # Dashboard BI 概览（放在 uuid 路由前，避免被 <uuid:dataset_id> 误匹配）
    path('stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    # 多数据集联合查询（同样放在 uuid 路由前）
    path('multi/', views.NL2SQLMultiQueryView.as_view(), name='nl2sql-multi-query'),
    path('history/', views.QueryHistoryView.as_view(), name='query-history'),
    path('history/<uuid:history_id>/rerun/', views.QueryRerunView.as_view(), name='query-rerun'),
    path('<uuid:query_id>/chart-suggest/', views.ChartSuggestView.as_view(), name='chart-suggest'),
    path('<uuid:dataset_id>/', views.NL2SQLQueryView.as_view(), name='nl2sql-query'),
]
