from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.datasets.api.views import DatasetViewSet

router = DefaultRouter()
router.register(r'', DatasetViewSet, basename='dataset')

urlpatterns = [
    path('', include(router.urls)),
]
