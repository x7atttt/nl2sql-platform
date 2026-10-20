# -*- coding: utf-8 -*-
"""外部数据源 API：CRUD / 连通测试 / 表浏览 / NL2SQL 查询。

权限模型（MVP）：数据源仅 owner 和 admin 可见可用（404 防枚举）；
创建/删除需 analyst 及以上；分享列为后续 spec。
"""
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsAnalyst, IsViewer
from apps.datasources.models import ExternalDataSource
from apps.datasources.api.serializers import (
    ExternalDataSourceSerializer,
    ExternalDataSourceCreateSerializer,
    ConnectionTestSerializer,
    ExternalQuerySerializer,
    ExternalDataSourceUpdateSerializer,
)
from apps.datasources.services.engine import (
    test_connection, encrypt_password,
)
from apps.datasources.services import introspect
from apps.datasources.services.nl2sql_external import ExternalNL2SQLService


def _get_own_source(user, source_id):
    """编辑/删除/重测用：owner 或 admin（共享读不共享写），否则 None。"""
    qs = ExternalDataSource.objects.all() if user.is_admin else \
        ExternalDataSource.objects.filter(owner=user)
    return qs.filter(id=source_id).first()


def _get_accessible_source(user, source_id):
    """读取/查询用：两态可见性（owner/admin/published），否则 None。"""
    from apps.datasources.services.access import get_accessible_source
    return get_accessible_source(user, source_id)


class DataSourceListCreateView(APIView):
    """GET 列表（两态可见性：owner 自己的+published / admin 全部）；POST 创建。"""
    def get_permissions(self):
        # 查看列表 viewer 也可（对话选源用）；建连接需 analyst
        if self.request.method == 'POST':
            return [IsAnalyst()]
        return [IsViewer()]

    def get(self, request):
        from apps.datasources.services.access import visible_sources_qs
        qs = visible_sources_qs(request.user).select_related('owner').order_by('-created_at')
        return Response(ExternalDataSourceSerializer(qs, many=True).data)

    def post(self, request):
        serializer = ExternalDataSourceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # 先测试连通，失败不落库（用户在对话框里就能看到具体错误）
        result = test_connection(
            d['db_type'], d['host'], d['port'], d['database'],
            d['username'], d['password'],
        )
        if not result['ok']:
            return Response({'error': f"连接失败：{result['error']}"},
                            status=status.HTTP_400_BAD_REQUEST)

        source = ExternalDataSource.objects.create(
            name=d['name'], db_type=d['db_type'], host=d['host'], port=d['port'],
            database=d['database'], username=d['username'],
            password_encrypted=encrypt_password(d['password']),
            business_description=d.get('business_description', ''),
            status='active', last_tested_at=timezone.now(),
            owner=request.user,
        )
        return Response(ExternalDataSourceSerializer(source).data,
                        status=status.HTTP_201_CREATED)


class DataSourceDetailView(APIView):
    """GET 详情（两态可见性）/ PATCH 改名·业务说明·发布 / DELETE（owner 或 admin）。"""
    permission_classes = [IsAnalyst]

    def get(self, request, source_id):
        source = _get_accessible_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ExternalDataSourceSerializer(source).data)

    def patch(self, request, source_id):
        source = _get_own_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = ExternalDataSourceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(source, field, value)
        source.save(update_fields=list(serializer.validated_data.keys())
                    + ['updated_at'])
        return Response(ExternalDataSourceSerializer(source).data)

    def delete(self, request, source_id):
        source = _get_own_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)
        introspect.invalidate_tables_cache(source.id)
        source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DataSourceTestParamsView(APIView):
    """POST /test-params/：保存前按连接参数测试（不落库）。"""
    permission_classes = [IsAnalyst]

    def post(self, request):
        serializer = ConnectionTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        result = test_connection(
            d['db_type'], d['host'], d['port'], d['database'],
            d['username'], d['password'],
        )
        if not result['ok']:
            return Response({'ok': False, 'error': result['error']},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class DataSourceTestView(APIView):
    """POST /{id}/test/：对已存数据源重测（解密凭据），更新状态。"""
    permission_classes = [IsAnalyst]

    def post(self, request, source_id):
        source = _get_own_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)
        from apps.datasources.services.engine import (
            create_engine_for_source, _classify_connection_error,
        )
        from sqlalchemy import text
        try:
            engine = create_engine_for_source(source)
            with engine.connect() as conn:
                version = conn.execute(text('SELECT VERSION()')).scalar()
            engine.dispose()
            source.status = 'active'
            source.last_tested_at = timezone.now()
            source.save(update_fields=['status', 'last_tested_at', 'updated_at'])
            return Response({'ok': True, 'server_version': str(version)})
        except Exception as e:  # noqa: BLE001 测试接口兜住所有驱动异常
            source.status = 'error'
            source.last_tested_at = timezone.now()
            source.save(update_fields=['status', 'last_tested_at', 'updated_at'])
            return Response({'ok': False,
                             'error': _classify_connection_error(e)},
                            status=status.HTTP_400_BAD_REQUEST)


class DataSourceTablesView(APIView):
    """GET /{id}/tables/：表结构浏览（表/列/注释/近似行数/文本列 top 值）。"""
    permission_classes = [IsViewer]

    def get(self, request, source_id):
        source = _get_accessible_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            overview = introspect.get_tables_overview(source)
        except Exception as e:  # noqa: BLE001 内省失败（连接断等）给可读错误
            return Response({'error': f'获取表结构失败：{e}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        tables = overview['tables']
        return Response({
            'count': len(tables),
            'over_limit': len(tables) > introspect.MAX_TABLES_IN_PROMPT,
            'max_tables': introspect.MAX_TABLES_IN_PROMPT,
            'tables': tables,
            'fk_hints': overview['fk_hints'],
        })


class DataSourceQueryView(APIView):
    """POST /{id}/query/：对外部数据源做自然语言查询（支持跨表 JOIN）。"""
    permission_classes = [IsViewer]

    def post(self, request, source_id):
        source = _get_accessible_source(request.user, source_id)
        if source is None:
            return Response({'error': '数据源不存在或无权访问'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = ExternalQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']
        tables = serializer.validated_data.get('tables')

        service = ExternalNL2SQLService(source, tables)
        result = service.query(question)

        # 查询历史（与文件数据集共用一张表；dataset 为空 + source 记录来源）
        from apps.query.models import QueryHistory
        is_success = result.get('success', False)
        data = result.get('data', []) if is_success else []
        history = QueryHistory.objects.create(
            dataset=None, source=source,
            source_tables=tables or None,
            user=request.user,
            question=question,
            generated_sql=result.get('sql', ''),
            is_success=is_success,
            error_message=result.get('error', ''),
            execution_time_ms=result.get('execution_time_ms'),
            result_count=len(data),
            result_preview=data[:20] if data else None,
            result_columns=list(data[0].keys()) if data else None,
        )
        result['query_id'] = str(history.id)
        result['source_id'] = str(source.id)
        return Response(result)
