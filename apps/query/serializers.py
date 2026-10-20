from rest_framework import serializers
from .models import QueryHistory


class NL2SQLQuerySerializer(serializers.Serializer):
    question = serializers.CharField(
        max_length=1000,
        required=True,
        help_text='自然语言查询问题',
    )


class NL2SQLMultiQuerySerializer(serializers.Serializer):
    """联合查询入参：2-3 个数据集 + 一个问题。

    上限 3 个：控制 prompt 长度（3 份 schema 摘要）和同表自连接规模。
    """
    dataset_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=2,
        max_length=3,
        required=True,
        help_text='参与联合查询的数据集 ID 列表（2-3 个）',
    )
    question = serializers.CharField(
        max_length=1000,
        required=True,
        help_text='自然语言查询问题',
    )


class QueryHistorySerializer(serializers.ModelSerializer):
    # 外部数据源查询 dataset 为 None，DRF 对 None 关系的点路径安全返回 None
    dataset_name = serializers.CharField(
        source='dataset.name', read_only=True, default=None
    )
    source_name = serializers.CharField(
        source='source.name', read_only=True, default=None,
        help_text='外部数据源名（外部查询时非空）'
    )
    source_db_type = serializers.CharField(
        source='source.db_type', read_only=True, default=None
    )
    username = serializers.CharField(
        source='user.username', read_only=True,
        help_text='查询发起人（admin 审计视角需要）'
    )

    class Meta:
        model = QueryHistory
        fields = (
            'id', 'dataset', 'dataset_name',
            'source', 'source_name', 'source_db_type', 'source_tables',
            'username', 'question',
            'generated_sql', 'is_success', 'error_message',
            'execution_time_ms',
            'result_count', 'result_preview', 'result_columns',
            'created_at',
        )
        read_only_fields = fields
