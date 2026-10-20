from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsViewer
from apps.datasets.models import Dataset
from apps.query.models import QueryHistory
from apps.query.serializers import (
    NL2SQLQuerySerializer, NL2SQLMultiQuerySerializer, QueryHistorySerializer,
)
from apps.query.services.nl2sql import NL2SQLService


def _all_history_datasets(history: QueryHistory) -> list:
    """历史查询涉及的全部数据集：联合查询取 M2M，单表查询退化为 FK。"""
    multi = list(history.datasets.all())
    return multi if multi else [history.dataset]


def _visibility_denied_dataset(user, history: QueryHistory):
    """复检历史查询全部数据集的可见性。

    联合查询撤销任一数据集的分享都应阻断访问（防止绕过单个数据集的
    撤销）。返回第一个不可见的数据集对象；全部可见返回 None。
    """
    from apps.datasets.services.visibility import can_access_dataset
    for ds in _all_history_datasets(history):
        if not can_access_dataset(user, ds):
            return ds
    return None


class NL2SQLQueryView(APIView):
    """自然语言查询接口"""
    permission_classes = [IsViewer]

    def post(self, request, dataset_id):
        serializer = NL2SQLQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        # 数据集可见性：复用公共方法，统一口径（修复各接口可见性不一致）
        # admin 任意 / analyst owner+shares / viewer 仅 shares
        from apps.datasets.services.visibility import get_accessible_dataset
        dataset = get_accessible_dataset(request.user, dataset_id)

        if dataset is None:
            return Response(
                {'error': '数据集不存在或无权访问'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if dataset.status != 'completed':
            return Response(
                {'error': '数据集尚未处理完成'}, status=status.HTTP_400_BAD_REQUEST
            )

        service = NL2SQLService(dataset)
        result = service.query(question)

        # 记录查询历史（成功查询持久化前 20 行预览，失败留 null）
        is_success = result.get('success', False)
        data = result.get('data', []) if is_success else []

        # 生成问题向量（用于 few-shot 语义检索；失败不阻塞，留 null）
        # 只有成功的查询才有作为 few-shot 案例的价值，失败的不生成
        from apps.query.services.embedding import embed_question
        question_embedding = embed_question(question) if is_success else None

        history = QueryHistory.objects.create(
            dataset=dataset,
            user=request.user,
            question=question,
            generated_sql=result.get('sql', ''),
            is_success=is_success,
            error_message=result.get('error', ''),
            execution_time_ms=result.get('execution_time_ms'),
            result_count=len(data),
            result_preview=data[:20] if data else None,
            result_columns=list(data[0].keys()) if data else None,
            question_embedding=question_embedding,
        )

        result['query_id'] = str(history.id)
        return Response(result)


class NL2SQLMultiQueryView(APIView):
    """多数据集联合查询接口。

    用户勾选 2-3 个数据集提问，LLM 基于各数据集 schema 摘要（含 top 值枚举）
    和"疑似关联列"提示自动推断 JOIN 条件，生成同表自连接 SQL
    （dataset_rows 不同别名 + 各自 dataset_id 过滤）。

    安全模型：
    1. 每个数据集独立过 get_accessible_dataset（任一无权 → 403）
    2. SQL 生成后 _validate_sql 做 dataset_id 白名单校验（防幻觉引用未授权数据集）
    """
    permission_classes = [IsViewer]

    def post(self, request):
        serializer = NL2SQLMultiQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dataset_ids = serializer.validated_data['dataset_ids']
        question = serializer.validated_data['question']

        # 逐数据集校验可见性 + 状态（口径与单数据集查询一致）
        from apps.datasets.services.visibility import get_accessible_dataset
        datasets = []
        for dataset_id in dataset_ids:
            ds = get_accessible_dataset(request.user, dataset_id)
            if ds is None:
                return Response(
                    {'error': f'数据集 {dataset_id} 不存在或无权访问'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if ds.status != 'completed':
                return Response(
                    {'error': f'数据集"{ds.name}"尚未处理完成'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            datasets.append(ds)

        # 去重（重复 ID 没意义还浪费 prompt）
        seen = set()
        datasets = [ds for ds in datasets if not (str(ds.id) in seen or seen.add(str(ds.id)))]
        if len(datasets) < 2:
            return Response(
                {'error': '联合查询至少需要 2 个不同的数据集'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = NL2SQLService(datasets)
        result = service.query(question)

        is_success = result.get('success', False)
        data = result.get('data', []) if is_success else []

        from apps.query.services.embedding import embed_question
        question_embedding = embed_question(question) if is_success else None

        history = QueryHistory.objects.create(
            dataset=datasets[0],       # FK 指向主数据集（第一个）
            user=request.user,
            question=question,
            generated_sql=result.get('sql', ''),
            is_success=is_success,
            error_message=result.get('error', ''),
            execution_time_ms=result.get('execution_time_ms'),
            result_count=len(data),
            result_preview=data[:20] if data else None,
            result_columns=list(data[0].keys()) if data else None,
            question_embedding=question_embedding,
        )
        # M2M 记录全部参与数据集（rerun/chart-suggest 复检用）
        history.datasets.set(datasets)

        result['query_id'] = str(history.id)
        return Response(result)


class QueryHistoryView(APIView):
    """查询历史列表"""
    permission_classes = [IsViewer]

    def get(self, request):
        # 权限隔离：admin 看全部用户的查询历史（用于审计/排查/使用分析，
        # 对标 Superset/Metabase）；非 admin 只看自己的（最小权限）。
        if request.user.is_admin:
            queryset = QueryHistory.objects.all()
        else:
            queryset = QueryHistory.objects.filter(user=request.user)
        queryset = queryset.select_related(
            'dataset', 'source', 'user',
        ).order_by('-created_at')

        dataset_id = request.query_params.get('dataset_id')
        if dataset_id:
            # 兼容联合查询：命中"主数据集(FK)"或"任一参与数据集(M2M)"的历史都返回
            from django.db.models import Q
            queryset = queryset.filter(
                Q(dataset_id=dataset_id) | Q(datasets__id=dataset_id)
            ).distinct()

        # 外部数据源筛选：?source_id=（与 dataset_id 互斥使用）
        source_id = request.query_params.get('source_id')
        if source_id:
            queryset = queryset.filter(source_id=source_id)

        # 搜索：?search=关键词，按问题文本模糊匹配（icontains）
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(question__icontains=search)

        try:
            page = int(request.query_params.get('page', 1))
        except (ValueError, TypeError):
            page = 1
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        total = queryset.count()
        records = queryset[start:end]

        serializer = QueryHistorySerializer(records, many=True)
        return Response({
            'count': total,
            'results': serializer.data,
            'page': page,
            'page_size': page_size,
        })


class QueryRerunView(APIView):
    """重跑历史查询：用历史记录里的 SQL 重新执行，返回完整结果（不落库）。

    场景：查询历史只存前 20 行预览，用户想看完整结果时点重跑。
    项目是"上传快照"模式，数据集不变，重跑结果与当时一致，所以无需缓存。
    复用 ExportService.execute_query（已含自动 LIMIT 1000）。
    """
    permission_classes = [IsViewer]

    def post(self, request, history_id):
        # 1. 取历史记录（admin 可重跑任意历史用于审计，非 admin 只能重跑自己的）
        if request.user.is_admin:
            history_qs = QueryHistory.objects.all()
        else:
            history_qs = QueryHistory.objects.filter(user=request.user)
        try:
            history = history_qs.get(id=history_id)
        except QueryHistory.DoesNotExist:
            return Response(
                {'error': '查询记录不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. 校验：只有当时成功的查询才能重跑
        if not history.is_success:
            return Response(
                {'error': '该查询当时执行失败，无法重跑'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2.5 外部数据源查询的重跑：走外部 engine 重新执行
        if history.dataset is None:
            return self._rerun_external(request, history)

        # 3. 校验：数据集是否还在（被删除的不能重跑；联合查询查全部参与数据集）
        related = _all_history_datasets(history)
        if not related or any(
            ds is None or ds.status != 'completed' for ds in related
        ):
            return Response(
                {'error': '数据集已不存在或状态异常，无法重跑'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3.1 可见性复检：撤销分享后历史记录仍在，但不能继续访问数据
        # （修复 Bug #2：撤销分享后 viewer 仍可 rerun 拿完整结果的数据泄露）
        # 联合查询对全部参与数据集复检——撤销任一数据集的分享都阻断
        denied = _visibility_denied_dataset(request.user, history)
        if denied is not None:
            return Response(
                {'error': f'你已无权访问数据集"{denied.name}"（分享可能已被撤销）'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 4. 重跑：复用 ExportService（已含自动 LIMIT 1000）
        from apps.export.services.exporter import ExportService
        try:
            data = ExportService.execute_query(history.generated_sql)
        except Exception as e:
            return Response(
                {'error': f'重跑失败：{e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 5. 返回完整结果（不存）
        return Response({
            'history_id': str(history.id),
            'question': history.question,
            'generated_sql': history.generated_sql,
            'data': data,
            'row_count': len(data),
        })

    def _rerun_external(self, request, history):
        """外部数据源查询的重跑：source 被删（SET_NULL 后为 None）→ 404；
        权限复检（owner/admin）→ 外部 engine 重新执行。"""
        if history.source is None:
            return Response(
                {'error': '外部数据源已被删除，无法重跑'},
                status=status.HTTP_404_NOT_FOUND,
            )
        source = history.source
        if not (request.user.is_admin or source.owner_id == request.user.id):
            return Response(
                {'error': '你已无权访问该数据源'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from apps.datasources.services.engine import create_engine_for_source
        from apps.datasources.services.nl2sql_external import execute_external_sql
        try:
            engine = create_engine_for_source(source)
            try:
                data, _column_types = execute_external_sql(
                    engine, history.generated_sql)
            finally:
                engine.dispose()
        except Exception as e:  # noqa: BLE001
            return Response(
                {'error': f'重跑失败：{e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({
            'history_id': str(history.id),
            'question': history.question,
            'generated_sql': history.generated_sql,
            'data': data,
            'row_count': len(data),
        })


class ChartSuggestView(APIView):
    """LLM 智能图表推荐接口（异步调用，前端拿到查询结果后单独请求）。

    流程：前端查询成功后 → 规则引擎先画默认图 → 同时发请求到本接口 →
    后端用 LLM 基于问题+SQL+列统计推荐图表 → 前端拿到后智能切换。

    失败降级：LLM 超时/非法 JSON → 返回 {success: false}，前端保持规则引擎图。
    参考 LIDA 的 Summary 模式 + Vanna 的混合策略。
    """
    permission_classes = [IsViewer]

    def post(self, request, query_id):
        # 1. 取查询历史（admin 全部/非 admin 自己的，与 QueryHistoryView 一致）
        if request.user.is_admin:
            history_qs = QueryHistory.objects.all()
        else:
            history_qs = QueryHistory.objects.filter(user=request.user)
        try:
            history = history_qs.select_related('dataset', 'source').get(id=query_id)
        except QueryHistory.DoesNotExist:
            return Response(
                {'error': '查询记录不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. 前置校验：只有成功的查询 + 数据集还在才能推荐
        if not history.is_success:
            return Response(
                {'error': '该查询当时执行失败，无法推荐图表'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2.5 外部数据源查询：走外部分支（权限复检 + 外部 engine 执行）
        if history.dataset is None:
            return self._suggest_external(request, history)

        if not history.dataset or history.dataset.status != 'completed':
            return Response(
                {'error': '数据集已不存在或状态异常'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 可见性复检：撤销分享后不能继续访问数据（修复数据泄露）
        # 联合查询对全部参与数据集复检——撤销任一数据集的分享都阻断
        denied = _visibility_denied_dataset(request.user, history)
        if denied is not None:
            return Response(
                {'error': f'你已无权访问数据集"{denied.name}"（分享可能已被撤销）'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not history.result_columns:
            return Response(
                {'success': False, 'reason': '查询无结果列，无法可视化'},
            )

        # 3. 重新执行 SQL 取 data + column_types（复用公共执行器）
        #    不用 result_preview（只有 20 行），LLM 需要完整结果统计
        from apps.query.services.nl2sql import execute_select_sql
        from apps.query.services.chart_advisor import suggest_chart
        try:
            data, column_types = execute_select_sql(
                history.generated_sql, infer_types=True,
            )
        except Exception as e:
            return Response(
                {'success': False, 'reason': f'重跑查询失败：{e}'},
            )

        if not data:
            return Response(
                {'success': False, 'reason': '查询结果为空，无法可视化'},
            )

        # 4. 调 LLM 推荐图表（失败返回 success: false，前端降级）
        # 联合查询合并全部参与数据集的业务说明，帮 LLM 理解 JOIN 结果字段语义
        multi = list(history.datasets.all())
        if multi:
            business_description = '\n'.join(
                f'数据集"{ds.name}": {ds.business_description.strip() or "无"}'
                for ds in multi
            )
        else:
            business_description = history.dataset.business_description
        suggestion = suggest_chart(
            question=history.question,
            sql=history.generated_sql,
            columns=list(data[0].keys()),
            column_types=column_types,
            data=data,
            business_description=business_description,
        )

        if suggestion is None:
            return Response({
                'success': False,
                'reason': 'LLM 推荐失败，已降级到规则引擎默认图',
            })

        return Response({
            'success': True,
            'suggestion': suggestion,
        })

    def _suggest_external(self, request, history):
        """外部数据源查询的图表推荐：source 校验/复检 → 外部 engine 重跑 → LLM 推荐。"""
        if history.source is None:
            return Response(
                {'success': False, 'reason': '外部数据源已被删除，无法推荐图表'},
            )
        source = history.source
        if not (request.user.is_admin or source.owner_id == request.user.id):
            return Response(
                {'success': False, 'reason': '你已无权访问该数据源'},
            )
        if not history.result_columns:
            return Response({'success': False, 'reason': '查询无结果列，无法可视化'})

        from apps.datasources.services.engine import create_engine_for_source
        from apps.datasources.services.nl2sql_external import execute_external_sql
        from apps.query.services.chart_advisor import suggest_chart
        try:
            engine = create_engine_for_source(source)
            try:
                data, column_types = execute_external_sql(
                    engine, history.generated_sql)
            finally:
                engine.dispose()
        except Exception as e:  # noqa: BLE001
            return Response({'success': False, 'reason': f'重跑查询失败：{e}'})

        if not data:
            return Response({'success': False, 'reason': '查询结果为空，无法可视化'})

        suggestion = suggest_chart(
            question=history.question,
            sql=history.generated_sql,
            columns=list(data[0].keys()),
            column_types=column_types,
            data=data,
            business_description=source.business_description,
        )
        if suggestion is None:
            return Response({
                'success': False,
                'reason': 'LLM 推荐失败，已降级到规则引擎默认图',
            })
        return Response({'success': True, 'suggestion': suggestion})


class DashboardStatsView(APIView):
    """Dashboard BI 概览聚合接口。

    GET /api/dashboard/stats/ —— 一次返回查询趋势（30 天）+ 数据集健康度 + 汇总卡片。
    权限分层对标 Power BI workspace 角色模型：
    admin 看全平台运营视角，analyst/viewer 看个人视角（详见 dashboard.py）。
    """
    permission_classes = [IsViewer]

    def get(self, request):
        from apps.query.services.dashboard import get_dashboard_stats
        stats = get_dashboard_stats(request.user)
        return Response(stats)
