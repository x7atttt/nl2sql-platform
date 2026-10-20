from rest_framework import serializers

from apps.datasources.models import ExternalDataSource
from apps.datasources.services.engine import DEFAULT_PORTS


class ExternalDataSourceSerializer(serializers.ModelSerializer):
    """数据源列表/详情序列化（绝不输出 password_encrypted）。"""
    owner_name = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model = ExternalDataSource
        fields = (
            'id', 'name', 'db_type', 'host', 'port', 'database', 'username',
            'business_description', 'visibility', 'status', 'last_tested_at',
            'owner', 'owner_name', 'created_at',
        )
        read_only_fields = fields


DB_TYPES = ['mysql', 'postgresql', 'sqlite', 'clickhouse']


def _normalize_conn_attrs(attrs: dict) -> dict:
    """端口缺省按类型补默认；SQLite（本地文件库）无主机/凭据概念，统一补空。"""
    db_type = attrs.get('db_type')
    if not attrs.get('port'):
        attrs['port'] = DEFAULT_PORTS.get(db_type) or 0
    if db_type == 'sqlite':
        attrs.setdefault('host', '')
        attrs.setdefault('username', '')
        attrs.setdefault('password', '')
    elif not attrs.get('host') or not attrs.get('username'):
        raise serializers.ValidationError('该数据库类型必须填写主机和用户名')
    return attrs


class ExternalDataSourceCreateSerializer(serializers.Serializer):
    """创建入参：连接信息 + 明文密码（只在内存停留，落库前加密）。"""
    name = serializers.CharField(max_length=255)
    db_type = serializers.ChoiceField(choices=DB_TYPES)
    host = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                 default='')
    port = serializers.IntegerField(min_value=0, max_value=65535, required=False)
    database = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                     default='')
    password = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                     default='', write_only=True)
    business_description = serializers.CharField(required=False, allow_blank=True,
                                                default='', max_length=2000)

    def validate(self, attrs):
        return _normalize_conn_attrs(attrs)


class ConnectionTestSerializer(serializers.Serializer):
    """保存前连通性测试入参（不落库）。"""
    db_type = serializers.ChoiceField(choices=DB_TYPES)
    host = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                 default='')
    port = serializers.IntegerField(min_value=0, max_value=65535, required=False)
    database = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                     default='')
    password = serializers.CharField(max_length=255, required=False, allow_blank=True,
                                     default='')

    def validate(self, attrs):
        return _normalize_conn_attrs(attrs)


class ExternalQuerySerializer(serializers.Serializer):
    """外部数据源查询入参。tables 在表数超上限（20）时必传。"""
    question = serializers.CharField(max_length=1000)
    tables = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False, allow_empty=False, max_length=20,
        help_text='指定查询涉及的表（库内表数超过 20 张时必传）',
    )


class ExternalDataSourceUpdateSerializer(serializers.Serializer):
    """编辑入参：只允许改名和业务说明（连接信息删了重建，避免半更新状态）。"""
    name = serializers.CharField(max_length=255, required=False)
    business_description = serializers.CharField(required=False, allow_blank=True,
                                                 default='', max_length=2000)
    visibility = serializers.ChoiceField(choices=['private', 'published'],
                                         required=False)
