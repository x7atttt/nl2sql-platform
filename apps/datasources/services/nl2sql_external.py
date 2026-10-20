# -*- coding: utf-8 -*-
"""外部数据源 NL2SQL：真实数据库上的自然语言查询（支持跨表 JOIN）。

与文件数据集路径（NL2SQLService）的对应关系：
- Schema 发现：analyzer JSONB 统计 → introspect 内省 + 采样
- SQL 校验：共用 validate_select_sql（外部路径无 dataset_id 白名单——engine 只连
  目标库，平台自身表从连接层不可达）
- 执行：Django cursor → SQLAlchemy engine
- JOIN 提示："疑似关联列"猜测 → 权威外键关系

方言差异（关键）：PostgreSQL 支持 ORDER BY ... NULLS LAST；MySQL 不支持该语法，
空值排后要用 ORDER BY (col IS NULL), col —— prompt 规则按方言注入。
"""
import logging
import time
from string import Template

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import text

from django.conf import settings

from apps.query.services.nl2sql import (
    _sanitize_for_json, _infer_py_types,
    validate_select_sql, add_limit_clause, check_duplicate_columns, clean_sql,
)

logger = logging.getLogger(__name__)

# 各方言的"空值排序"规则片段（PG 默认 DESC 时 NULL 在前；MySQL 语法不支持 NULLS LAST）
_NULLS_RULES = {
    'postgresql': '使用 ORDER BY 排序时必须加 NULLS LAST（PostgreSQL 默认 DESC 时 NULL 排最前）',
    'mysql': 'MySQL 不支持 NULLS LAST 语法；想让空值排最后用 ORDER BY (列名 IS NULL), 列名',
    'sqlite': '使用 ORDER BY 排序时必须加 NULLS LAST（SQLite 默认 ASC 时 NULL 排最前）',
    'clickhouse': 'ClickHouse 默认 NULL 已排在最后，且支持 ORDER BY ... NULLS LAST 语法',
}

SQL_GENERATE_EXTERNAL_SYSTEM = Template("""你是一个专业的SQL生成助手。根据以下信息生成SQL查询。

数据存储在真实的$db_type_name数据库中，表和列都是真实存在的（列有类型）。

$schema_summary

规则:
1. 只生成 SELECT 语句
2. 直接用表名.列名引用（数值列有类型，直接比较，无需类型转换）
3. 跨表问题用 JOIN，关联条件优先使用上方"外键关系"
4. 文本列的 top 值是 WHERE 条件取值参考（照着写命中率高）
5. 大表（行数多）优先 GROUP BY 聚合后再输出，避免返回明细
6. 所有 SELECT 列加 AS 别名（用简洁英文），尤其跨表查询时防止列名重复
7. 不要使用 LIMIT 以外的结果限制方式
8. $nulls_rule
""")

SQL_FIX_EXTERNAL_SYSTEM = Template("""你是一个SQL修复专家。之前生成的SQL在$db_type_name数据库上执行失败了，请根据错误信息修复SQL。

$schema_summary

规则:
1. 只生成 SELECT 语句，直接用表名.列名
2. 跨表 JOIN 优先使用"外键关系"
3. 所有 SELECT 列加 AS 别名
4. $nulls_rule
""")

SQL_GENERATE_USER = Template("用户问题: $question\n\n请生成SQL查询（只输出SQL语句，不要解释）:")
SQL_FIX_USER = Template("问题: $question\n\n失败的SQL: $failed_sql\n\n错误信息: $error_msg\n\n请生成修复后的SQL（只输出SQL语句）:")

_DB_TYPE_NAMES = {'mysql': 'MySQL', 'postgresql': 'PostgreSQL',
                  'sqlite': 'SQLite', 'clickhouse': 'ClickHouse'}


def _escape_braces(s: str) -> str:
    return s.replace('{', '{{').replace('}', '}}')


def execute_external_sql(engine, sql: str) -> tuple:
    """在外部 engine 上执行只读 SQL，返回 (净化后 rows, 列类型映射)。

    复用查询服务的净化/类型推断/重复列名检测，保证与文件路径行为一致。
    """
    # ClickHouse 只读加固在执行层注入 per-query settings（方言不透传 connect
    # 级 settings，且 text() 编译路径会绕过会话 SET——实测结论）
    with engine.connect() as conn:
        if engine.dialect.name == 'clickhouse':
            conn = conn.execution_options(
                settings={'readonly': 1, 'max_execution_time': 30})
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchall()

    check_duplicate_columns(columns)
    column_types = _infer_py_types(columns, rows)
    sanitized = [_sanitize_for_json(dict(zip(columns, row))) for row in rows]
    return sanitized, column_types


class ExternalNL2SQLService:
    """外部数据源自然语言查询（生成 → 只读校验 → LIMIT → 执行 → 失败重试）。"""

    MAX_RETRIES = 3

    def __init__(self, source, tables: list | None = None):
        self.source = source
        self.tables = tables  # None = 全部表（≤20 张）；超出由调用方先筛选
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_API_BASE,
        )

    def _generate_sql(self, question: str, schema_summary: str) -> str:
        prompt = ChatPromptTemplate.from_messages([
            ('system', _escape_braces(SQL_GENERATE_EXTERNAL_SYSTEM.safe_substitute(
                db_type_name=_DB_TYPE_NAMES[self.source.db_type],
                schema_summary=schema_summary,
                nulls_rule=_NULLS_RULES[self.source.db_type],
            ))),
            ('human', _escape_braces(SQL_GENERATE_USER.safe_substitute(question=question))),
        ])
        response = (prompt | self.llm).invoke({})
        return clean_sql(response.content)

    def _regenerate_sql(self, question: str, failed_sql: str,
                        error_msg: str, schema_summary: str) -> str:
        prompt = ChatPromptTemplate.from_messages([
            ('system', _escape_braces(SQL_FIX_EXTERNAL_SYSTEM.safe_substitute(
                db_type_name=_DB_TYPE_NAMES[self.source.db_type],
                schema_summary=schema_summary,
                nulls_rule=_NULLS_RULES[self.source.db_type],
            ))),
            ('human', _escape_braces(SQL_FIX_USER.safe_substitute(
                question=question, failed_sql=failed_sql, error_msg=error_msg,
            ))),
        ])
        response = (prompt | self.llm).invoke({})
        return clean_sql(response.content)

    def query(self, question: str) -> dict:
        """执行查询。返回结构与 NL2SQLService.query 对齐（前端无感复用）。"""
        from apps.datasources.services.introspect import build_external_schema_summary
        from apps.datasources.services.engine import create_engine_for_source

        start_time = time.time()

        # 1. Schema 发现（内省 + 缓存；空库/表超限在此抛 ValueError 给调用方）
        try:
            schema_summary = build_external_schema_summary(self.source, self.tables)
        except ValueError as e:
            return {'success': False, 'error': str(e), 'sql': '',
                    'retry_count': 0,
                    'execution_time_ms': int((time.time() - start_time) * 1000)}

        engine = create_engine_for_source(self.source)
        try:
            # 2. 生成 → 3. 只读校验 → 4. LIMIT → 5. 执行 + 重试
            sql = self._generate_sql(question, schema_summary)

            if not validate_select_sql(sql):
                return {'success': False, 'sql': sql,
                        'error': '生成的SQL包含不允许的操作，仅支持SELECT查询',
                        'retry_count': 0,
                        'execution_time_ms': int((time.time() - start_time) * 1000)}
            # AST 沙箱：单语句/SELECT/表白名单（防正则被注释/CTE 绕过）
            from apps.query.services.nl2sql import SQLGLOT_DIALECTS
            from apps.query.services.sql_sandbox import sandbox_check_sql
            from apps.datasources.services.introspect import get_tables_overview
            allowed = {t['name'] for t in get_tables_overview(self.source)['tables']}
            sandbox_reason = sandbox_check_sql(
                sql, allowed, SQLGLOT_DIALECTS[self.source.db_type])
            if sandbox_reason:
                return {'success': False, 'sql': sql,
                        'error': f'SQL 安全沙箱拒绝：{sandbox_reason}',
                        'retry_count': 0,
                        'execution_time_ms': int((time.time() - start_time) * 1000)}

            sql = add_limit_clause(sql, 1000)

            retry_count = 0
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    results, column_types = execute_external_sql(engine, sql)
                    return {
                        'sql': sql, 'success': True, 'retry_count': retry_count,
                        'execution_time_ms': int((time.time() - start_time) * 1000),
                        'data': results, 'row_count': len(results),
                        'column_types': column_types,
                    }
                except Exception as e:
                    retry_count += 1
                    logger.warning('外部SQL执行失败 (尝试 %d/%d): %s',
                                   retry_count, self.MAX_RETRIES, e)
                    if attempt < self.MAX_RETRIES:
                        sql = self._regenerate_sql(
                            question, sql, str(e), schema_summary)
                        if not validate_select_sql(sql):
                            return {'success': False, 'sql': sql,
                                    'error': '修复后的SQL仍包含不允许的操作',
                                    'retry_count': retry_count,
                                    'execution_time_ms':
                                        int((time.time() - start_time) * 1000)}
                        sql = add_limit_clause(sql, 1000)
                    else:
                        return {'sql': sql, 'success': False, 'error': str(e),
                                'retry_count': retry_count,
                                'execution_time_ms':
                                    int((time.time() - start_time) * 1000)}
        finally:
            engine.dispose()
