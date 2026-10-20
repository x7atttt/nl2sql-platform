# -*- coding: utf-8 -*-
"""外部数据源连接层：凭据加密（Fernet）+ SQLAlchemy engine 工厂 + 连通性测试。

安全设计：
- password 落库为 Fernet 密文，密钥来自环境变量 DATASOURCE_ENC_KEY（独立于
  SECRET_KEY，可单独轮换）。密钥未配置时创建数据源报错，不影响平台其余功能。
- engine 用 NullPool（连接即建即用，免连接池维护——个人项目并发低）+
  connect_timeout=5（防慢连接挂死请求）。
- 平台隔离：engine 只连目标库，平台自身的表（用户/数据集）从连接层不可达。
"""
import logging

import redis as redis_lib
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from django.conf import settings

logger = logging.getLogger(__name__)


class EncryptionKeyMissingError(RuntimeError):
    """DATASOURCE_ENC_KEY 未配置。"""

    def __init__(self):
        super().__init__(
            'DATASOURCE_ENC_KEY 未配置。请执行 '
            '"python -c \\"from cryptography.fernet import Fernet; print(Fernet.generate_key())\\"" '
            '生成密钥并写入 .env（形如 DATASOURCE_ENC_KEY=xxxx）'
        )


def get_fernet():
    from cryptography.fernet import Fernet
    key = getattr(settings, 'DATASOURCE_ENC_KEY', '') or ''
    if not key:
        raise EncryptionKeyMissingError()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_password(plain: str) -> str:
    return get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(token: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError('密码解密失败：DATASOURCE_ENC_KEY 与加密时不一致') from e


# db_type → SQLAlchemy dialect
_DIALECTS = {
    'mysql': 'mysql+pymysql',
    'postgresql': 'postgresql+psycopg2',
    # clickhouse+native：二进制协议（clickhouse-driver），不依赖 requests
    'clickhouse': 'clickhouse+native',
    # SQLite：服务器本地库文件，database 字段存绝对路径
    'sqlite': 'sqlite',
}

DEFAULT_PORTS = {'mysql': 3306, 'postgresql': 5432, 'clickhouse': 9000}

# 连通性测试的版本探测 SQL（SQLite 无 VERSION() 函数）
_VERSION_SQL = {
    'sqlite': 'SELECT sqlite_version()',
}


def build_url(db_type: str, host: str, port: int, database: str,
              username: str, password: str) -> str:
    from urllib.parse import quote_plus
    dialect = _DIALECTS[db_type]
    if db_type == 'sqlite':
        # sqlite:///绝对路径（database 即文件路径，无主机/凭据）
        return f'sqlite:///{database}'
    return (
        f'{dialect}://{quote_plus(username)}:{quote_plus(password)}'
        f'@{host}:{port}/{database}'
    )


def create_engine_for(db_type: str, host: str, port: int, database: str,
                      username: str, password: str) -> Engine:
    """按连接参数创建 engine（创建前测试连通 / 查询时按需创建共用此入口）。"""
    url = build_url(db_type, host, port, database, username, password)
    connect_args = {'connect_timeout': 5}
    if db_type == 'mysql':
        connect_args['charset'] = 'utf8mb4'
    elif db_type == 'sqlite':
        connect_args = {'timeout': 5}  # sqlite3 锁等待秒数
    return create_engine(url, poolclass=NullPool, connect_args=connect_args)


def create_engine_for_source(source) -> Engine:
    """从 ExternalDataSource 模型实例创建 engine。"""
    return create_engine_for(
        source.db_type, source.host, source.port,
        source.database, source.username, decrypt_password(source.password_encrypted),
    )


def _classify_connection_error(e: Exception) -> str:
    """把驱动异常翻译成用户可读的错误类型（认证失败 / 网络失败 / 其他）。"""
    msg = str(e)
    if 'Access denied' in msg or 'password authentication' in msg:
        return f'认证失败（用户名或密码错误）：{msg}'
    if any(k in msg.lower() for k in
           ('connect', 'refused', 'reachable', 'timeout', 'timed out',
            'name or service', '拒绝', '无法连接')):
        return f'网络连接失败（主机/端口不可达或超时）：{msg}'
    if 'database' in msg.lower() and ('exist' in msg.lower() or 'unknown' in msg.lower()):
        return f'数据库不存在：{msg}'
    return msg


def test_connection(db_type: str, host: str, port: int, database: str,
                    username: str, password: str) -> dict:
    """测试连通性，返回 {'ok': bool, 'server_version': str?, 'error': str?}。

    不抛异常——错误分类后返回，供创建对话框直接展示。
    """
    try:
        engine = create_engine_for(db_type, host, port, database, username, password)
        with engine.connect() as conn:
            version = conn.execute(
                text(_VERSION_SQL.get(db_type, 'SELECT VERSION()'))).scalar()
        engine.dispose()
        return {'ok': True, 'server_version': str(version)}
    except Exception as e:  # noqa: BLE001 连通性测试要兜住所有驱动异常
        logger.warning('datasource test failed: %s', e)
        return {'ok': False, 'error': _classify_connection_error(e)}
