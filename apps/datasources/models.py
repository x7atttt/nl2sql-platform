import uuid

from django.conf import settings
from django.db import models


class ExternalDataSource(models.Model):
    """外部数据库连接（MySQL / PostgreSQL），作为与文件上传平行的数据源路径。

    凭据安全：password 字段存 Fernet 密文（密钥来自 DATASOURCE_ENC_KEY 环境变量），
    任何序列化输出都不包含 password。
    隔离：查询走 SQLAlchemy engine 只连目标库——平台自身数据库从连接层就不可达。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name='数据源名称')
    db_type = models.CharField(max_length=20, choices=[
        ('mysql', 'MySQL'), ('postgresql', 'PostgreSQL'),
        ('sqlite', 'SQLite'), ('clickhouse', 'ClickHouse'),
    ], verbose_name='数据库类型')
    host = models.CharField(max_length=255, verbose_name='主机')
    port = models.IntegerField(verbose_name='端口')
    database = models.CharField(max_length=255, verbose_name='数据库名')
    username = models.CharField(max_length=255, verbose_name='用户名')
    password_encrypted = models.TextField(verbose_name='密码（Fernet 密文）')
    business_description = models.TextField(
        blank=True, default='', verbose_name='业务说明',
        help_text='库/表的业务背景，注入 NL2SQL prompt 帮助理解字段语义',
    )
    status = models.CharField(max_length=20, choices=[
        ('active', '可用'), ('error', '连接失败'),
    ], default='active', verbose_name='状态')
    last_tested_at = models.DateTimeField(null=True, blank=True, verbose_name='最近连通测试时间')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='datasources', verbose_name='所属用户',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'external_data_sources'
        verbose_name = '外部数据源'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['owner', 'created_at'], name='idx_ds_owner_created'),
        ]

    def __str__(self):
        return f'{self.name}({self.db_type}://{self.host}/{self.database})'
