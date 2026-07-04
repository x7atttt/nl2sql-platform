"""数据集可见性判断（RBAC 核心）。

抽成公共函数，避免各接口各自重写过滤逻辑导致口径不一致。
所有需要判断"某用户能否访问某数据集"的接口都应调 can_access_dataset，
不要在各 view 里手写 owner/shares 过滤。

口径统一（与 DatasetViewSet.get_queryset 三分支一致）：
- admin：全部数据集
- analyst：owner=self 的 + 被分享给自己的
- viewer：被分享给自己的（不含 owner——viewer 无上传权限，不应有 owner 数据集；
  若因角色降级产生 viewer 拥有的数据集，按"严格隔离"原则不在列表展示，
  但历史查询仍可见，避免数据完全消失）

关于 analyst 合并 shares 的决策：
  原口径 analyst 只认 owner，导致分享给 analyst 形同虚设（能分享却不能用）。
  统一为 analyst 也认 shares，让分享对 analyst 生效，与 share 接口对齐。
"""
from apps.datasets.models import Dataset


def can_access_dataset(user, dataset) -> bool:
    """判断 user 当前是否有权访问 dataset（实时校验，不依赖 QueryHistory）。

    用于 NL2SQL 查询 / 重跑 / 导出 / 图表推荐等下游接口，确保撤销分享后
    历史查询记录不能继续访问数据（修复"撤销分享后仍可 rerun/export"的泄露）。

    Args:
        user: 已认证用户
        dataset: Dataset 实例（或 None）

    Returns:
        True 如果 user 当前有权访问该数据集
    """
    if dataset is None:
        return False
    if user.is_admin:
        return True
    if user.is_analyst:
        # analyst：自己 owner 的 + 被分享给自己的
        return dataset.owner_id == user.id or dataset.shares.filter(shared_to=user).exists()
    # viewer：仅被分享给自己的（严格隔离，不含 owner）
    return dataset.shares.filter(shared_to=user).exists()


def get_accessible_dataset(user, dataset_id) -> Dataset | None:
    """按可见性取单个数据集，不可见返回 None。

    供下游接口使用：取不到（None）时调用方应返回 404。
    比 can_access_dataset 少一次 DB 查询（直接按可见性 filter）。
    """
    qs = Dataset.objects.all() if user.is_admin else (
        Dataset.objects.filter(owner=user) if user.is_analyst else Dataset.objects.none()
    )
    if user.is_analyst:
        # analyst 合并被分享的
        from django.db.models import Q
        qs = Dataset.objects.filter(Q(owner=user) | Q(shares__shared_to=user)).distinct()
    elif not user.is_admin:
        qs = Dataset.objects.filter(shares__shared_to=user).distinct()
    return qs.filter(id=dataset_id).first()
