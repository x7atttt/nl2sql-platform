from django.urls import path
from . import views

urlpatterns = [
    path('history/', views.QueryHistoryView.as_view(), name='query-history'),
    path('history/<uuid:history_id>/rerun/', views.QueryRerunView.as_view(), name='query-rerun'),
    path('<uuid:dataset_id>/', views.NL2SQLQueryView.as_view(), name='nl2sql-query'),
]
