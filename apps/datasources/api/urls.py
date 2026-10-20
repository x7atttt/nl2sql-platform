from django.urls import path
from . import views

urlpatterns = [
    # 固定路径放 uuid 路由前，避免被 <uuid:source_id> 误匹配
    path('test-params/', views.DataSourceTestParamsView.as_view(),
         name='datasource-test-params'),
    path('', views.DataSourceListCreateView.as_view(), name='datasource-list-create'),
    path('<uuid:source_id>/', views.DataSourceDetailView.as_view(),
         name='datasource-detail'),
    path('<uuid:source_id>/test/', views.DataSourceTestView.as_view(),
         name='datasource-test'),
    path('<uuid:source_id>/tables/', views.DataSourceTablesView.as_view(),
         name='datasource-tables'),
    path('<uuid:source_id>/query/', views.DataSourceQueryView.as_view(),
         name='datasource-query'),
]
