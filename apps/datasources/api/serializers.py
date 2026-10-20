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
            'business_description', 'status', 'last_tested_at',
            'owner', 'owner_name', 'created_at',
        )
        read_only_fields = fields


class ExternalDataSourceCreateSerializer(serializers.Serializer):
    """创建入参：连接信息 + 明文密码（只在内存停留，落库前加密）。"""
    name = serializers.CharField(max_length=255)
    db_type = serializers.ChoiceField(choices=['mysql', 'postgresql'])
    host = serializers.CharField(max_length=255)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    database = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=255)
    password = serializers.CharField(max_length=255, write_only=True)
    business_description = serializers.CharField(required=False, allow_blank=True,
                                                default='', max_length=2000)

    def validate(self, attrs):
        # 端口缺省按类型补默认
        if not attrs.get('port'):
            attrs['port'] = DEFAULT_PORTS[attrs['db_type']]
        return attrs


class ConnectionTestSerializer(serializers.Serializer):
    """保存前连通性测试入参（不落库）。"""
    db_type = serializers.ChoiceField(choices=['mysql', 'postgresql'])
    host = serializers.CharField(max_length=255)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    database = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=255)
    password = serializers.CharField(max_length=255)

    def validate(self, attrs):
        if not attrs.get('port'):
            attrs['port'] = DEFAULT_PORTS[attrs['db_type']]
        return attrs


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
