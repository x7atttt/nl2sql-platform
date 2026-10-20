import uuid
from django.db import models
from django.conf import settings
from pgvector.django import VectorField, HnswIndex


class QueryHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 文件数据集查询走 dataset；外部数据源查询 dataset 为空、走 source。
    # 两条数据源路径共用一张历史表，前端查询历史一个列表展示。
    dataset = models.ForeignKey(
        'datasets.Dataset', on_delete=models.CASCADE,
        related_name='queries', null=True, blank=True,
    )
    source = models.ForeignKey(
        'datasources.ExternalDataSource', on_delete=models.SET_NULL,
        related_name='queries', null=True, blank=True,
        verbose_name='外部数据源（外部查询时记录）',
    )
    # 外部查询本次涉及的表清单（如 ["orders", "customers"]），重跑/审计用
    source_tables = models.JSONField(
        null=True, blank=True, verbose_name='外部查询涉及表',
    )
    # 联合查询参与的全部数据集（dataset FK 指向第一个/主数据集）。
    # 单数据集查询此 M2M 为空；rerun/chart-suggest 复检时对 M2M 全量校验可见性。
    datasets = models.ManyToManyField(
        'datasets.Dataset', related_name='multi_queries', blank=True,
        verbose_name='参与数据集（联合查询）',
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
    # 问题的向量表示（1024 维，模型见 settings.EMBEDDING_MODEL），用于 few-shot 语义检索
    # null=未生成（查询失败或 embedding 接口异常时不写），检索时 filter 排除
    question_embedding = VectorField(
        dimensions=1024, null=True, blank=True, verbose_name='问题向量'
    )
    # 该条历史的 SQL 跑在哪个引擎上（重跑/导出/图表复检按此分派执行器）：
    # platform-pg=JSONB 旧路径 / duckdb=物化数据集 / mysql|postgresql=外部源
    execution_engine = models.CharField(
        max_length=20, default='platform-pg', verbose_name='执行引擎',
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


class TraceSpan(models.Model):
    """可追溯 span：一轮对话/查询的每个关键步骤（LLM 调用/校验/执行/向量化）一条记录。

    trace_id 由 ChatService 每轮生成，写入 assistant 消息 extra.trace_id，
    前端"过程"Tab 按 trace_id 拉时间线。参考 DB-GPT 的 trace_id 贯穿设计，
    但用轻量表存储替代 OpenTelemetry 全家桶（项目规模不需要跨服务传播）。
    """
    id = models.BigAutoField(primary_key=True)
    trace_id = models.UUIDField(verbose_name='追溯ID', db_index=True)
    span_type = models.CharField(
        max_length=20,
        choices=[
            ('llm', 'LLM 调用'),
            ('sql_validate', 'SQL 校验'),
            ('sql_execute', 'SQL 执行'),
            ('embed', '向量化'),
            ('materialize', '数据物化'),
            ('skill', '技能'),
        ],
        verbose_name='步骤类型',
    )
    name = models.CharField(max_length=100, verbose_name='步骤名')
    status = models.CharField(max_length=10,
                              choices=[('ok', '成功'), ('error', '失败')],
                              verbose_name='状态')
    duration_ms = models.IntegerField(verbose_name='耗时(ms)')
    # 摘要属性（不含完整 prompt，防膨胀与敏感信息）：模型名/prompt 字符数/
    # token 用量/SQL/重试轮次/错误信息等
    attributes = models.JSONField(null=True, blank=True, verbose_name='属性摘要')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'trace_spans'
        verbose_name = '追溯Span'
        verbose_name_plural = verbose_name
        ordering = ['id']


class Conversation(models.Model):
    """对话会话：产品主交互单元（chat_file 绑定文件数据集 / chat_db 绑定外部数据源）。

    visibility 字段是两态权限模型（private/published）的先行落位——
    门禁暂不启用（登录即可对话），字段先到位避免日后加门禁时再迁移。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='conversations', verbose_name='所属用户',
    )
    chat_mode = models.CharField(
        max_length=20,
        choices=[('chat_file', '文件数据集对话'), ('chat_db', '外部数据源对话')],
        verbose_name='对话场景',
    )
    dataset = models.ForeignKey(
        'datasets.Dataset', on_delete=models.CASCADE,
        related_name='conversations', null=True, blank=True,
    )
    source = models.ForeignKey(
        'datasources.ExternalDataSource', on_delete=models.CASCADE,
        related_name='conversations', null=True, blank=True,
    )
    title = models.CharField(max_length=200, blank=True, default='', verbose_name='会话标题')
    visibility = models.CharField(
        max_length=20,
        choices=[('private', '私有'), ('published', '已发布')],
        default='private', verbose_name='可见性',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_conversations'
        verbose_name = '对话会话'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['user', 'updated_at'], name='idx_conv_user_updated'),
        ]


class ChatMessage(models.Model):
    """对话消息。user 存问题原文；assistant 的 content 存 thoughts，
    extra 存结构化载荷（sql/chart_type/结果行）——图表数据存这里但不回传 LLM
    （回传只有 token 成本没有收益，DB-GPT 同款经验）。
    """
    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages',
    )
    round_index = models.IntegerField(verbose_name='轮次')
    role = models.CharField(
        max_length=10, choices=[('user', '用户'), ('assistant', '助手')],
    )
    content = models.TextField(verbose_name='内容')
    extra = models.JSONField(null=True, blank=True, verbose_name='结构化载荷')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_messages'
        verbose_name = '对话消息'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(
                fields=['conversation', 'round_index'],
                name='idx_chatmsg_conv_round',
            ),
        ]
