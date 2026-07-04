from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsViewer
from apps.datasets.models import Dataset
from apps.query.models import QueryHistory
from apps.query.serializers import NL2SQLQuerySerializer, QueryHistorySerializer
from apps.query.services.nl2sql import NL2SQLService


class NL2SQLQueryView(APIView):
    """自然语言查询接口"""
    permission_classes = [IsViewer]

    def post(self, request, dataset_id):
        serializer = NL2SQLQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        # 数据集可见性：与 DatasetViewSet.get_queryset 分层一致
        # admin 任意、analyst 只查自己的、viewer 只查被分享的
        user = request.user
        if user.is_admin:
            dataset = Dataset.objects.filter(id=dataset_id).first()
        elif user.is_analyst:
            dataset = Dataset.objects.filter(id=dataset_id, owner=user).first()
        else:  # viewer
            from django.db.models import Q
            dataset = Dataset.objects.filter(
                Q(owner=user) | Q(shares__shared_to=user)
            ).filter(id=dataset_id).distinct().first()

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
        queryset = queryset.select_related('dataset', 'user').order_by('-created_at')

        dataset_id = request.query_params.get('dataset_id')
        if dataset_id:
            queryset = queryset.filter(dataset_id=dataset_id)

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

        # 3. 校验：数据集是否还在（被删除的不能重跑）
        if not history.dataset or history.dataset.status != 'completed':
            return Response(
                {'error': '数据集已不存在或状态异常，无法重跑'},
                status=status.HTTP_404_NOT_FOUND,
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
            history = history_qs.select_related('dataset').get(id=query_id)
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
        if not history.dataset or history.dataset.status != 'completed':
            return Response(
                {'error': '数据集已不存在或状态异常'},
                status=status.HTTP_404_NOT_FOUND,
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
        suggestion = suggest_chart(
            question=history.question,
            sql=history.generated_sql,
            columns=list(data[0].keys()),
            column_types=column_types,
            data=data,
            business_description=history.dataset.business_description,
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
