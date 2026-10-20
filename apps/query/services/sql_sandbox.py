# -*- coding: utf-8 -*-
"""SQL 沙箱：在既有四层正则校验之上的第二层保障（defense in depth）。

参考分层（业界沙箱共识 + DB-GPT 反面教训——其 DML 直执行无任何防护）：
1. AST 级校验（sqlglot）：正则可被注释/CTE/嵌套构造绕过；AST 无歧义——
   单语句 + 根节点必须是 SELECT + 全部表引用必须在白名单内
2. 会话只读加固（engine 层）：即使校验被绕过，连接本身拒绝写入
   （PG default_transaction_read_only + statement_timeout；MySQL 会话事务
   READ ONLY；SQLite URI mode=ro；ClickHouse settings readonly=1）
3. 敏感列脱敏（结果层，Metabase Data Sandbox 思路的最小实现）：
   命中敏感列名模式的值在返回给非 admin 用户前打码

三层各司其职：AST 挡"不该执行的语句"，只读会话挡"绕过校验的写入"，
脱敏挡"合法查询带出的敏感数据"。
"""
import logging
import re

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# 敏感列名模式（命中即对非 admin 打码；大小写不敏感，中英文都覆盖）
SENSITIVE_COLUMN_RE = re.compile(
    r'password|passwd|pwd|secret|token|api_key|apikey|'
    r'手机号|手机|phone|mobile|'
    r'身份证|id_?card|'
    r'银行卡|bank_?card|card_?no',
    re.IGNORECASE,
)

MASK = '***'


# ===== 1. AST 级校验 =====

def sandbox_check_sql(sql: str, allowed_tables: set[str],
                      dialect: str) -> str | None:
    """AST 级 SQL 沙箱校验。通过返回 None，不通过返回原因（中文，可直接喂重试）。

    Args:
        allowed_tables: 允许引用的表（无库前缀的裸名和 db.table 限定名都比对）
        dialect: sqlglot 方言（duckdb/mysql/postgres/sqlite/clickhouse）
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        return f'SQL 解析失败（沙箱拒绝）: {str(e)[:200]}'
    statements = [st for st in statements if st is not None]
    if len(statements) != 1:
        return f'必须恰好是一条语句，实际 {len(statements)} 条'
    root = statements[0]
    # 只允许纯查询树：SELECT / UNION（of SELECT）。
    # 正则层挡不住的 "WITH x AS (...) DELETE ..." 在这里根节点是 Delete
    if not isinstance(root, (exp.Select, exp.Union, exp.Subquery)):
        return f'只允许 SELECT 查询，实际语句类型: {type(root).__name__}'
    if isinstance(root, exp.Subquery) and not isinstance(
            root.this, (exp.Select, exp.Union)):
        return '只允许 SELECT 查询'

    for table in root.find_all(exp.Table):
        ref = f'{table.db}.{table.name}' if table.db else table.name
        # 严格匹配：带库/模式前缀的引用必须全限定相等（防 t3.data 借裸名 data 放行）；
        # 裸表名按白名单内的裸名比对
        if ref not in allowed_tables:
            return f'引用了未授权的表: {ref}'
    return None


# ===== 2. 敏感列脱敏 =====

def mask_sensitive_columns(rows: list[dict], user) -> list[dict]:
    """结果行脱敏：敏感列名的值打码。admin 不脱敏（管理审计需要看全量）。"""
    if not rows or user is None or getattr(user, 'is_admin', False):
        return rows
    sensitive = [c for c in rows[0].keys() if SENSITIVE_COLUMN_RE.search(str(c))]
    if not sensitive:
        return rows
    for row in rows:
        for col in sensitive:
            if row.get(col) is not None:
                row[col] = MASK
    return rows


def mask_columns_for(columns: list[str], user) -> list[str]:
    """列名级判断（视图层提示用）：该用户视角下哪些列会被脱敏。"""
    if user is None or getattr(user, 'is_admin', False):
        return []
    return [c for c in columns if SENSITIVE_COLUMN_RE.search(str(c))]
