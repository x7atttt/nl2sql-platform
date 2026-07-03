import uuid
from django.db import models
from django.conf import settings
from pgvector.django import VectorField, HnswIndex


class QueryHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(
        'datasets.Dataset', on_delete=models.CASCADE, related_name='queries'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='queries'
    )
    question = models.TextField(verbose_name='自然语言问题')
    generated_sql = models.TextField(verbose_name='生成的SQL')
    is_success = models.BooleanField(default=False, verbose_name='是否成功')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    execution_time_ms = models.IntegerField(null=True, verbose_name='执行时间(ms)')
    result_count = models.IntegerField(default=0, verbose_name='结果行数')
    result_preview = models.JSONField(null=True, blank=True, verbose_name='结果预览(前20行)')
    result_columns = models.JSONField(null=True, blank=True, verbose_name='结果列名')
    # 问题的向量表示（智谱 embedding-3，1024 维），用于 few-shot 语义检索
    # 用 1024 而非默认 2048：HNSW 索引限制 ≤2000 维，且 1024 对几百条 few-shot 检索精度足够
    # null=未生成（查询失败或 embedding 接口异常时不写），检索时 filter 排除
    question_embedding = VectorField(
        dimensions=1024, null=True, blank=True, verbose_name='问题向量'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'query_history'
        verbose_name = '查询历史'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(
                fields=['dataset', 'created_at'],
                name='idx_query_dataset_created',
            ),
            # HNSW 索引加速语义检索（few-shot 按问题向量相似度取最近 3 条）
            # cosine 距离对应归一化向量的点积，embedding-3 默认输出已归一化
            HnswIndex(
                name='idx_query_embedding_hnsw',
                fields=['question_embedding'],
                opclasses=['vector_cosine_ops'],
            ),
        ]
