from urllib.parse import quote

from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsViewer
from apps.query.models import QueryHistory
from apps.export.services.exporter import ExportService


class ExportView(APIView):
    """数据导出接口（CSV/Excel）

    根据 query_id 重新执行历史 SQL 并导出。
    权限：任意登录用户（导出是只读操作——重跑 SELECT 取完整结果落盘，
    viewer 本身就能查询，允许导出合理；数据范围仍按 user 隔离）。
    """
    permission_classes = [IsViewer]

    def get(self, request, query_id, fmt):
        if fmt not in ('csv', 'xlsx'):
            return Response(
                {'error': '不支持的格式，仅支持 csv/xlsx'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 权限隔离：admin 可导出任意查询（审计/排查），非 admin 只能导出自己的。
        # 与 QueryHistoryView 的可见性逻辑对齐（避免 admin 能看历史却不能导出的不一致）
        if request.user.is_admin:
            query_qs = QueryHistory.objects.all()
        else:
            query_qs = QueryHistory.objects.filter(user=request.user)
        try:
            query = query_qs.get(id=query_id)
        except QueryHistory.DoesNotExist:
            return Response(
                {'error': '查询记录不存在'}, status=status.HTTP_404_NOT_FOUND
            )

        if not query.is_success:
            return Response(
                {'error': '该查询未成功执行，无法导出'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 可见性复检：撤销分享后历史记录仍在，但不能继续导出数据
        # （修复 Bug #2：撤销分享后 viewer 仍可 export 拿完整数据的数据泄露）
        from apps.datasets.services.visibility import can_access_dataset
        if not can_access_dataset(request.user, query.dataset):
            return Response(
                {'error': '你已无权访问该数据集（分享可能已被撤销）'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 重新执行 SQL 获取数据
        try:
            data = ExportService.execute_query(query)
        except Exception as e:
            return Response(
                {'error': f'重新执行查询失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not data:
            return Response(
                {'error': '查询结果为空，无法导出'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 导出
        dataset_name = query.dataset.name.replace(' ', '_')
        filename_csv = quote(f'{dataset_name}_result.csv')
        filename_xlsx = quote(f'{dataset_name}_result.xlsx')
        if fmt == 'csv':
            content = ExportService.export_csv(data)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = (
                f"attachment; filename*=UTF-8''{filename_csv}"
            )
        else:
            content = ExportService.export_excel(data)
            response = HttpResponse(
                content,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = (
                f"attachment; filename*=UTF-8''{filename_xlsx}"
            )

        return response
