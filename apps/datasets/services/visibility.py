"""资源可见性判断（两态权限模型核心）。

口径（见 spec/2026-10-20-permission-design.md）：
- admin：全部资源
- owner：永远能访问自己的资源（所有权与角色解耦，降级不丢访问权）
- 其他用户：仅 visibility='published' 的资源

历史注记：此前为 per-user DatasetShare 授权（analyst 把数据集逐个分享给 viewer），
该机制已冻结——存量 share 记录在 migration 中一次性转换为 published，此后
"分享"语义由发布开关承载。所有需要判断"能否访问"的接口统一调本模块，
不要在 view 里手写 owner/visibility 过滤。
"""
from django.db.models import Q

from apps.datasets.models import Dataset


def can_access_dataset(user, dataset) -> bool:
    """判断 user 当前是否有权访问 dataset（实时校验，不依赖 QueryHistory）。

    用于 NL2SQL 查询 / 对话 / 重跑 / 导出 / 图表推荐等接口，确保取消发布后
    历史查询记录不能继续访问数据。
    """
    if dataset is None:
        return False
    if user.is_admin:
        return True
    if dataset.owner_id == user.id:
        return True
    return dataset.visibility == 'published'


def get_accessible_dataset(user, dataset_id) -> Dataset | None:
    """按可见性取单个数据集，不可见返回 None（调用方应返回 404）。"""
    return visible_datasets_qs(user).filter(id=dataset_id).first()


def visible_datasets_qs(user):
    """当前用户可见的数据集查询集（列表接口用）。"""
    if user.is_admin:
        return Dataset.objects.all()
    return Dataset.objects.filter(
        Q(owner=user) | Q(visibility='published')
    ).distinct()
