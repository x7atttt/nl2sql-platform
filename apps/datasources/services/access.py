"""数据源连接的可见性判断（与 datasets.visibility 同款两态模型）。

此前为 owner-only（admin 例外），团队无法共享连接；现改为
private/published：owner 永远可见，published 全员可查询/可开对话，
编辑/删除仍限 owner 与 admin（共享读不共享写）。
"""
from django.db.models import Q

from apps.datasources.models import ExternalDataSource


def can_access_source(user, source) -> bool:
    if source is None:
        return False
    if user.is_admin:
        return True
    if source.owner_id == user.id:
        return True
    return source.visibility == 'published'


def get_accessible_source(user, source_id) -> ExternalDataSource | None:
    return visible_sources_qs(user).filter(id=source_id).first()


def visible_sources_qs(user):
    if user.is_admin:
        return ExternalDataSource.objects.all()
    return ExternalDataSource.objects.filter(
        Q(owner=user) | Q(visibility='published')
    ).distinct()
