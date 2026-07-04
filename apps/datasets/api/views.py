import hashlib

from django.db import IntegrityError
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from apps.users.permissions import IsAnalyst, IsViewer
from apps.datasets.models import Dataset
from apps.datasets.serializers import DatasetSerializer
from apps.datasets.services.upload_lock import UploadLockService
from apps.datasets.services.parser import ALLOWED_EXTENSIONS

SMALL_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB，与 Nginx client_max_body_size 对齐


class DatasetViewSet(viewsets.ModelViewSet):
    """数据集管理接口：上传/列表/详情/删除"""

    serializer_class = DatasetSerializer
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_permissions(self):
        if self.action in ('create', 'destroy', 'update', 'partial_update', 'share', 'shares', 'unshare', 'shareable_users'):
            return [IsAnalyst()]
        return [IsViewer()]

    def get_queryset(self):
        from django.db.models import Q
        user = self.request.user
        if user.is_admin:
            # admin 看全部（管理需要）
            return Dataset.objects.all().order_by('-created_at')
        if user.is_analyst:
            # analyst：自己 owner 的 + 被分享给自己的（与 get_accessible_dataset 口径一致）
            # 之前只认 owner，导致 analyst 被分享的数据集列表看不到但能查（口径不一致）
            return Dataset.objects.filter(
                Q(owner=user) | Q(shares__shared_to=user)
            ).distinct().order_by('-created_at')
        # viewer：只看被分享给自己的（严格隔离，不含 owner）
        return Dataset.objects.filter(
            shares__shared_to=user
        ).distinct().order_by('-created_at')

    def create(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': '请选择文件'}, status=status.HTTP_400_BAD_REQUEST
            )

        ext = _get_extension(file.name)
        if ext not in ALLOWED_EXTENSIONS:
            return Response(
                {'error': f'不支持的文件格式，仅支持 {", ".join(ALLOWED_EXTENSIONS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 文件大小校验（与 Nginx client_max_body_size 对齐，
        # 本地开发无 Nginx 时这层兜底，保证本地/生产行为一致）
        if file.size > MAX_FILE_SIZE:
            return Response(
                {'error': f'文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 上限'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # 流式计算 MD5
        file_md5 = _compute_md5(file)
        file.seek(0)

        lock_service = UploadLockService()
        user_id = request.user.id

        # 先获取分布式锁，再查库（避免并发请求都通过 is_duplicate）
        if not lock_service.try_acquire_lock(user_id, file_md5):
            return Response(
                {'error': '该文件正在处理中'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            # 在锁内查库，保证原子性
            if lock_service.is_duplicate(user_id, file_md5):
                return Response(
                    {'error': '该文件已存在', 'file_md5': file_md5},
                    status=status.HTTP_409_CONFLICT,
                )

            try:
                dataset = Dataset.objects.create(
                    name=request.data.get('name') or file.name,
                    description=request.data.get('description', ''),
                    business_description=request.data.get('business_description', ''),
                    file=file,
                    file_name=file.name,
                    file_size=file.size,
                    file_md5=file_md5,
                    owner=request.user,
                )
            except IntegrityError:
                return Response(
                    {'error': '该文件已存在'},
                    status=status.HTTP_409_CONFLICT,
                )

            if file.size < SMALL_FILE_THRESHOLD:
                from apps.datasets.services.parser import parse_file_sync
                parse_file_sync(dataset)
            else:
                from apps.datasets.tasks import process_large_file
                process_large_file.delay(str(dataset.id))

            serializer = DatasetSerializer(dataset)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        finally:
            lock_service.release_lock(user_id, file_md5)

    def destroy(self, request, *args, **kwargs):
        dataset = self.get_object()
        # 失效 schema 缓存（数据集要删了，缓存的 schema 摘要没意义了）
        from apps.datasets.services.analyzer import invalidate_schema_cache
        invalidate_schema_cache(dataset.id)
        dataset.file.delete(save=False)
        dataset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def partial_update(self, request, *args, **kwargs):
        """部分更新数据集（当前仅允许改 business_description）。

        白名单防越权：前端只能改业务说明，file/owner/status 等敏感字段
        即使传了也会被忽略。权限走 get_queryset 隔离（admin 任意 / analyst
        仅自己 owner 的）。
        """
        dataset = self.get_object()
        # 白名单：只允许改业务说明（其他字段即使传了也忽略）
        allowed_fields = {'business_description'}
        update_fields = {k: v for k, v in request.data.items() if k in allowed_fields}
        if not update_fields:
            return Response(
                {'error': '没有可更新的字段（仅支持 business_description）'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for field, value in update_fields.items():
            setattr(dataset, field, value)
        dataset.save(update_fields=list(update_fields.keys()) + ['updated_at'])
        serializer = self.get_serializer(dataset)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='analysis')
    def analysis(self, request, pk=None):
        """数据集分析统计"""
        dataset = self.get_object()
        if dataset.status != 'completed':
            return Response(
                {'error': '数据集尚未处理完成'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.datasets.services.analyzer import (
            get_dataset_overview, get_column_stats, _load_dataframe,
        )
        # 一次加载，overview 和 column_stats 共享（避免 50000 行加载 2 次）
        loaded = _load_dataframe(dataset)
        return Response({
            'overview': get_dataset_overview(dataset, loaded=loaded),
            'column_stats': get_column_stats(dataset, loaded=loaded),
        })

    @action(detail=True, methods=['post'], url_path='share')
    def share(self, request, pk=None):
        """analyst 把数据集分享给指定用户（viewer）。

        分享 = 可见性授权：viewer 默认看不到任何数据集，必须被 analyst
        显式分享后才能查询。对齐 Superset/Metabase 的 Viewer 授权机制。
        """
        dataset = self.get_object()  # 走 get_queryset，analyst 只能分享自己的

        target_user_id = request.data.get('user_id')
        if not target_user_id:
            return Response(
                {'error': '请提供 user_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.users.models import User
        try:
            target = User.objects.get(id=target_user_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': '目标用户不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if target.id == request.user.id:
            return Response(
                {'error': '不能分享给自己'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.datasets.models import DatasetShare
        share, created = DatasetShare.objects.get_or_create(
            dataset=dataset,
            shared_to=target,
            defaults={'shared_by': request.user, 'permission': 'query'},
        )
        if not created:
            return Response(
                {'message': '已分享过，无需重复'},
                status=status.HTTP_200_OK,
            )
        return Response(
            {'message': f'已分享给 {target.username}'},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'], url_path='shareable_users')
    def shareable_users(self, request):
        """获取可分享的用户列表（analyst/admin 可调）。

        分享弹窗需要这个接口拉取用户列表做下拉。只返回 id + username +
        role，避免泄露手机号/邮箱等敏感信息。排除当前用户自己（不能分享给自己）。
        """
        from apps.users.models import User
        users = User.objects.filter(is_active=True).exclude(id=request.user.id)
        return Response([
            {'id': u.id, 'username': u.username, 'role': u.role}
            for u in users
        ])

    @action(detail=True, methods=['get'], url_path='shares')
    def shares(self, request, pk=None):
        """查看某数据集分享给了谁（admin 任意 / analyst 仅自己 owner 的）。

        走 self.get_object() 复用 get_queryset 权限隔离——analyst 拿不到
        别人的数据集，自然看不到别人的分享记录。
        """
        dataset = self.get_object()
        shares = (
            dataset.shares
            .select_related('shared_to', 'shared_by')
            .order_by('-created_at')
        )
        return Response([self._serialize_share(s) for s in shares])

    @action(detail=False, methods=['get'], url_path='shares_list')
    def shares_list(self, request):
        """跨数据集的全局分享记录列表（侧边栏「分享记录」页用）。

        按角色范围隔离：
        - admin：全平台所有分享记录（数据治理审计）
        - analyst：自己 owner 的数据集的分享记录（我分享出去了什么）
        - viewer：被分享给自己的记录（谁分享给我的）
        """
        from apps.datasets.models import DatasetShare
        user = request.user
        qs = DatasetShare.objects.select_related('dataset', 'shared_to', 'shared_by')
        if user.is_admin:
            pass  # 全部
        elif user.is_analyst:
            qs = qs.filter(dataset__owner=user)
        else:  # viewer
            qs = qs.filter(shared_to=user)
        shares = qs.order_by('-created_at')
        return Response([self._serialize_share(s, include_dataset=True) for s in shares])

    @staticmethod
    def _serialize_share(s, include_dataset=False):
        """序列化 DatasetShare（复用于 shares 和 shares_list 两个接口）。"""
        data = {
            'id': str(s.id),
            'shared_to': {
                'id': s.shared_to.id,
                'username': s.shared_to.username,
                'role': s.shared_to.role,
            },
            'shared_by': {
                'id': s.shared_by.id,
                'username': s.shared_by.username,
            },
            'permission': s.permission,
            'created_at': s.created_at.isoformat(),
        }
        if include_dataset:
            data['dataset'] = {
                'id': str(s.dataset.id),
                'name': s.dataset.name,
            }
        return data

    @action(detail=True, methods=['delete'], url_path='shares/(?P<share_id>[^/.]+)')
    def unshare(self, request, pk=None, share_id=None):
        """撤销某数据集的单条分享（admin 任意 / analyst 仅自己 owner 的）。

        走 self.get_object() 权限隔离。撤销 = 删 DatasetShare 记录，
        viewer 可见性靠 shares__shared_to 反查，删后该 viewer 立即看不到该数据集。
        DatasetShare.id 是自增整数（非 UUID），非法 id 格式返回 404 而非 500。
        """
        dataset = self.get_object()
        try:
            deleted, _ = dataset.shares.filter(id=share_id).delete()
        except (ValueError, TypeError):
            # 非整数 id（如 UUID 字符串）——记录必然不存在
            deleted = 0
        if not deleted:
            return Response(
                {'error': '分享记录不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({'message': '已撤销分享'})


def _compute_md5(file) -> str:
    md5_hash = hashlib.md5()
    for chunk in file.chunks():
        md5_hash.update(chunk)
    return md5_hash.hexdigest()


def _get_extension(filename: str) -> str:
    return '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
