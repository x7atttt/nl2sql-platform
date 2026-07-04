"""数据集可见性判断（RBAC 核心）。

抽成公共函数，避免各接口各自重写过滤逻辑导致口径不一致。
所有需要判断"某用户能否访问某数据集"的接口都应调 can_access_dataset，
不要在各 view 里手写 owner/shares 过滤。

口径统一（对标 Tableau 的"所有权与角色解耦"原则）：
- admin：全部数据集
- owner：永远能访问自己 owner 的数据集（无论当前角色）
  → 解决 analyst 降级成 viewer 后 owner 数据集变孤儿的问题
  → 所有权和角色独立：角色决定"能做什么操作"，所有权决定"拥有什么资源"
- analyst：owner=self 的 + 被分享给自己的
- viewer：仅被分享给自己的（不含 owner——viewer 无上传权限，
  但因上面的 owner 原则，若因降级产生 viewer 拥有的数据集，仍能访问）
"""
from django.db.models import Q

from apps.datasets.models import Dataset


def can_access_dataset(user, dataset) -> bool:
    """判断 user 当前是否有权访问 dataset（实时校验，不依赖 QueryHistory）。

    用于 NL2SQL 查询 / 重跑 / 导出 / 图表推荐等下游接口，确保撤销分享后
    历史查询记录不能继续访问数据（修复"撤销分享后仍可 rerun/export"的泄露）。

    口径（对标 Tableau，所有权与角色解耦）：
    - admin 全部可见
    - owner 永远能访问自己的数据（无论当前角色，降级不丢数据）
    - 其余按角色：analyst 认 shares，viewer 认 shares

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
    # owner 永远能访问自己的数据（对标 Tableau，降级不丢数据访问权）
    if dataset.owner_id == user.id:
        return True
    # analyst/viewer：被分享给自己的（角色只决定操作权限，不决定 owner 数据访问权）
    return dataset.shares.filter(shared_to=user).exists()


def get_accessible_dataset(user, dataset_id) -> Dataset | None:
    """按可见性取单个数据集，不可见返回 None。

    供下游接口使用：取不到（None）时调用方应返回 404。
    口径与 can_access_dataset 一致（owner 永远可见 + shares）。
    """
    # owner 永远可见：用 Q(owner=user) | Q(shares__shared_to=user) 覆盖所有角色
    # admin 的 owner 分支天然包含（admin 的数据集 owner 是自己）
    if user.is_admin:
        qs = Dataset.objects.all()
    else:
        # analyst/viewer 统一：owner=self 或被分享给自己的
        # （analyst 和 viewer 的区别只在"能做什么操作"，不在"能访问什么数据"）
        qs = Dataset.objects.filter(
            Q(owner=user) | Q(shares__shared_to=user)
        ).distinct()
    return qs.filter(id=dataset_id).first()
