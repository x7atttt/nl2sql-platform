import re
import time
import logging
import json
from decimal import Decimal
from datetime import datetime, date
from string import Template

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from django.conf import settings
from django.db import connection

from apps.query.models import QueryHistory

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj):
    """递归把数据库返回的非 JSON 原生类型转成可序列化的类型。

    PostgreSQL cursor 返回的行里常含 Decimal（numeric 列）、
    datetime/date（时间列）、UUID 等，这些标准 json.dumps 不认识，
    直接塞进 JSONField 会抛 TypeError。统一在这里净化，让结果既能
    存 result_preview，也能直接走 DRF Response。
    """
    if isinstance(obj, Decimal):
        # Decimal → float（数值语义保留，舍弃精确精度，前端展示足够）
        return float(obj)
    if isinstance(obj, (datetime, date)):
        # datetime/date → ISO 格式字符串（前端可解析）
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


# SQL 中是否已有 LIMIT 子句的判断（用正则词边界，避免误判 'PRELIMITED' 等子串）
_HAS_LIMIT_RE = re.compile(r'\blimit\b\s+\d+', re.IGNORECASE)

# SQL 里 uuid 字面量（带引号），用于 dataset_id 白名单校验
_UUID_RE = re.compile(
    r"'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'"
)

# 危险关键字（只读校验：文件数据集路径与外部数据源路径共用）
DANGEROUS_KEYWORDS = [
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER',
    'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE',
    'GRANT', 'REVOKE',
]


def strip_sql_comments(sql: str) -> str:
    """剥离 SQL 注释后再做关键字校验，避免注释里的词被误判。

    支持两种 PostgreSQL/MySQL 注释：
    - 块注释  /* ... */（可跨行）
    - 行注释  -- ... 到行尾
    """
    sql = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)
    sql = re.sub(r'--[^\n]*', ' ', sql)
    return sql


def validate_select_sql(sql: str, allowed_dataset_ids: set | None = None) -> bool:
    """只读 SQL 校验（四层基础 + 可选 dataset_id 白名单层）。

    文件数据集路径与外部数据源路径共用；外部路径不传 allowed_dataset_ids
    （外部 engine 只连目标库，平台自身表从连接层就不可达）。

    1. 白名单：必须以 SELECT 开头
    2. 危险关键字：词边界匹配（防 'CREATED_AT' 误判 'CREATE'）
    3. 分号注入：SQL 中间不能有分号
    4. dataset_id 白名单（可选）：uuid 字面量必须在授权集合内
    """
    sql_clean = strip_sql_comments(sql).strip()
    sql_upper = sql_clean.upper()

    if not sql_upper.startswith('SELECT'):
        return False

    for keyword in DANGEROUS_KEYWORDS:
        if re.search(rf'\b{keyword}\b', sql_upper):
            return False

    if ';' in sql_clean.rstrip(';').rstrip():
        return False

    if allowed_dataset_ids is not None:
        sql_uuids = {m.lower() for m in _UUID_RE.findall(sql_clean)}
        if sql_uuids - allowed_dataset_ids:
            return False

    return True


def check_duplicate_columns(columns: list) -> None:
    """重复结果列名检测（JOIN 查询忘写 AS 别名时防 dict 静默丢列）。

    抛 ValueError，调用方让它进入失败重试循环，错误信息喂 LLM 自动补别名。
    """
    dup = {c for c in columns if columns.count(c) > 1}
    if dup:
        raise ValueError(
            f"结果列名重复: {', '.join(sorted(dup))}。"
            f'请为每个 SELECT 列添加不同的 AS 别名（如 SUM(amount) AS total_amount）'
        )


def add_limit_clause(sql: str, limit: int = 1000) -> str:
    """无 LIMIT 时追加保护上限（词边界判断，防列名含 limit 子串误判）。"""
    if not _HAS_LIMIT_RE.search(sql):
        sql = sql.rstrip(';') + f' LIMIT {limit}'
    return sql


def clean_sql(sql: str) -> str:
    """剥离 LLM 响应里的 markdown 代码围栏。"""
    sql = sql.strip()
    if sql.startswith('```'):
        sql = sql.split('\n', 1)[1] if '\n' in sql else sql[3:]
    if sql.endswith('```'):
        sql = sql.rsplit('```', 1)[0]
    return sql.strip()


def execute_duckdb_sql(dataset, sql: str):
    """在数据集物化的 DuckDB 文件上执行只读 SQL（对话/重跑/导出共用）。

    只读短连接（见 materialize.connect_readonly），连接层即数据隔离——
    只挂载该数据集文件，平台库与其他数据集不可达。
    """
    from apps.datasets.services.materialize import connect_readonly
    with connect_readonly(dataset) as con:
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()

    check_duplicate_columns(columns)
    column_types = _infer_py_types(columns, rows)
    sanitized = [_sanitize_for_json(dict(zip(columns, row))) for row in rows]
    return sanitized, column_types


def execute_duckdb_multi_sql(datasets: list, sql: str):
    """多数据集联邦执行：内存连接 ATTACH 各数据集库文件（t1/t2/t3 只读）。

    连接层隔离：只挂载参与数据集的文件，SQL 引用其他库/平台表不可达。
    """
    import duckdb as duckdb_lib
    from apps.datasets.services.materialize import duckdb_path
    con = duckdb_lib.connect()
    try:
        for i, ds in enumerate(datasets, 1):
            con.execute(f"ATTACH '{duckdb_path(ds)}' AS t{i} (READ_ONLY)")
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
    finally:
        con.close()

    check_duplicate_columns(columns)
    column_types = _infer_py_types(columns, rows)
    sanitized = [_sanitize_for_json(dict(zip(columns, row))) for row in rows]
    return sanitized, column_types


def execute_select_sql(sql: str, infer_types: bool = False):
    """执行 SELECT SQL 并返回净化后的结果行。

    NL2SQL 查询 / 重跑 / 导出共用此函数，避免三处重复 cursor+sanitize 实现。

    Args:
        sql: SELECT SQL（调用方负责安全校验和白名单）
        infer_types: True 时额外返回列类型映射（number/text/date/boolean），
                     供前端图表选型。类型在 sanitize 前推断（sanitize 后丢失）。

    Returns:
        infer_types=False → list[dict]
        infer_types=True  → (list[dict], dict[col, type])
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchall()

    # 重复列名检测：联合查询若 LLM 忘写 AS 别名，两数据集同名列（如 amount）
    # 会让下游 dict(zip(columns, row)) 静默丢列。显式抛错进入失败重试循环，
    # 错误信息会反馈给 LLM 让它补别名修复。
    check_duplicate_columns(columns)

    if infer_types:
        column_types = _infer_py_types(columns, rows)
        sanitized = [_sanitize_for_json(dict(zip(columns, row))) for row in rows]
        return sanitized, column_types

    return [_sanitize_for_json(dict(zip(columns, row))) for row in rows]


def _infer_py_types(columns: list, rows: list) -> dict:
    """从结果行推断每列简化类型：number / text / date / boolean。

    遍历该列直到找到第一个非 None 值判断类型（首行可能为空）。
    模块级函数，供 execute_select_sql 和 NL2SQLService 共用。
    """
    type_map = {}
    for col_idx, col_name in enumerate(columns):
        resolved = 'text'  # 兜底（空列或全 None）
        for row in rows:
            val = row[col_idx]
            if val is None:
                continue
            if isinstance(val, bool):
                resolved = 'boolean'
            elif isinstance(val, (int, float, Decimal)):
                resolved = 'number'
            elif isinstance(val, (datetime, date)):
                resolved = 'date'
            else:
                resolved = 'text'
            break
        type_map[col_name] = resolved
    return type_map


# ===== Prompt 模板化管理 =====

# DuckDB 物化方言规则（NL2SQLService 与 ChatService 共用单一来源）
DUCKDB_SQL_RULES = """- 数据已物化为 DuckDB 表 data（列有真实类型），直接用列名引用，数值列直接比较，无需类型转换
- 表名固定为 data（FROM data）；中文/特殊列名用双引号引用，如 "区域"
- 不要使用 LIMIT 以外的结果限制方式
- ORDER BY 排序时加 NULLS LAST（避免空值占满 LIMIT 结果）"""

SQL_GENERATE_SYSTEM = Template("""你是一个专业的SQL生成助手。根据以下信息生成SQL查询。

数据已物化为 DuckDB 表 data（每数据集一个库文件，列有真实类型）。

$schema_summary

业务说明（数据字典/字段业务含义，帮助理解数据语义）:
$business_description

相似查询案例:
$few_shot_cases

规则:
1. 只生成 SELECT 语句，直接用列名引用（数值列直接比较，无需类型转换）
2. 中文/特殊列名用双引号引用，如 "区域"
3. 不要使用 LIMIT 以外的结果限制方式
4. ORDER BY 排序时加 NULLS LAST（避免空值占满 LIMIT 结果）
""")

# 存量未迁移数据集的 JSONB 方言（惰性物化失败的回退路径）
SQL_GENERATE_LEGACY_SYSTEM = Template("""你是一个专业的SQL生成助手。根据以下信息生成PostgreSQL SQL查询。

数据存储在 dataset_rows 表中，每行数据存储在 data 字段(JSONB)中。

$schema_summary

业务说明（数据字典/字段业务含义，帮助理解数据语义）:
$business_description

相似查询案例:
$few_shot_cases

规则:
1. 只生成 SELECT 语句
2. 使用 data->>'列名' 获取文本值，data->'列名' 获取JSON值
3. 如需数值比较，使用 (data->>'列名')::numeric
4. 不要使用 LIMIT 以外的结果限制方式
5. 必须包含 WHERE dataset_id = '$dataset_id' 条件
6. 使用 ORDER BY 排序时必须加 NULLS LAST（PostgreSQL 默认 DESC 时 NULL 排最前，会让空值占满 LIMIT 结果）
""")

SQL_GENERATE_USER = Template("用户问题: $question\n\n请生成SQL查询（只输出SQL语句，不要解释）:")

SQL_FIX_SYSTEM = Template("""你是一个SQL修复专家。之前生成的SQL执行失败了，请根据错误信息修复SQL。

$schema_summary

规则:
1. ORDER BY 排序时必须加 NULLS LAST
""")

# ===== 多数据集联合查询 prompt =====

SQL_GENERATE_MULTI_SYSTEM = Template("""你是一个专业的SQL生成助手。根据以下信息生成SQL查询。

多个数据集各自物化为 DuckDB 表：别名 t1/t2/t3 对应各自库文件中的表 t{n}.data
（列有真实类型）。跨数据集问题用 JOIN 关联。

$schema_summary

各数据集业务说明:
$business_description

相似查询案例:
$few_shot_cases

规则:
1. 只生成 SELECT 语句
2. 每个数据集的表写成"FROM t1.data t1"（库名.表名 + 同名别名），列引用用别名前缀，
   如 t1.列名；中文/特殊列名用双引号，如 t1."区域"
3. JOIN 条件优先使用上方"疑似关联列"提示；没有提示时根据列语义和 top 值自行判断
4. 所有 SELECT 列必须加 AS 别名，用简洁英文（不同数据集可能有同名列，不加别名会报"列名重复"错误）
5. 优先"各自 GROUP BY 聚合后再 JOIN"，避免两个大数据集直接 JOIN 导致行数爆炸
6. 不要使用 LIMIT 以外的结果限制方式
7. ORDER BY 排序时必须加 NULLS LAST
""")

# 存量未迁移数据集的多表 JSONB 方言（回退路径）
SQL_GENERATE_MULTI_LEGACY_SYSTEM = Template("""你是一个专业的SQL生成助手。根据以下信息生成PostgreSQL SQL查询。

多个数据集存储在同一张 dataset_rows 表中（每行数据在 data 字段 JSONB 里），
用"别名 + dataset_id 过滤"区分各数据集的行，跨数据集问题用 JOIN 关联。

$schema_summary

各数据集业务说明:
$business_description

相似查询案例:
$few_shot_cases

规则:
1. 只生成 SELECT 语句
2. 列引用必须带别名前缀，如 t1.data->>'列名'；数值计算用 (t1.data->>'列名')::numeric
3. 每个用到的别名都必须带 dataset_id 过滤条件，如 WHERE t1.dataset_id = '...' AND t2.dataset_id = '...'
4. JOIN 条件优先使用上方"疑似关联列"提示；没有提示时根据列语义和 top 值自行判断
5. 所有 SELECT 列必须加 AS 别名，用简洁英文（不同数据集可能有同名列，不加别名会报"列名重复"错误）
6. 优先"各自 GROUP BY 聚合后再 JOIN"，避免两个大数据集直接 JOIN 导致行数爆炸
7. 不要使用 LIMIT 以外的结果限制方式
8. ORDER BY 排序时必须加 NULLS LAST
""")

SQL_FIX_MULTI_SYSTEM = Template("""你是一个SQL修复专家。之前生成的多数据集联合SQL执行失败了，请根据错误信息修复SQL。

$schema_summary

规则:
1. 每个数据集的表写成"FROM t1.data t1"（库名.表名 + 同名别名），列引用用别名前缀，
   所有 SELECT 列必须有 AS 别名
2. ORDER BY 排序时必须加 NULLS LAST
""")

SQL_FIX_USER = Template("问题: $question\n\n失败的SQL: $failed_sql\n\n错误信息: $error_msg\n\n请生成修复后的SQL（只输出SQL语句）:")


class NL2SQLService:
    """自然语言转SQL服务

    7步工作流：Schema发现→SQL生成→安全验证→执行→失败重试→结果格式化

    三个增强设计:
    1. Prompt 模板化 — string.Template，方便迭代调优
    2. Few-shot 案例库 — 从 QueryHistory 注入成功查询案例
    3. Analyzer 驱动的 Schema 发现 — 统计摘要 + 样本 + 字段值，替代简陋的手动探测

    支持单数据集（传 Dataset）和多数据集联合查询（传 list[Dataset]）：
    多数据集走同表自连接（dataset_rows 不同别名 + dataset_id 过滤），
    JOIN 条件由 LLM 根据"疑似关联列"提示和 top 值分布自动推断。
    """

    MAX_RETRIES = 3

    def __init__(self, dataset):
        # 兼容单 Dataset 和 list[Dataset]；多数据集时第一个是主数据集
        self.datasets = list(dataset) if isinstance(dataset, (list, tuple)) else [dataset]
        self.dataset = self.datasets[0]
        self.is_multi = len(self.datasets) > 1
        # dataset_id 白名单：SQL 中出现的 uuid 字面量必须都在这里
        # （防 LLM 幻觉引用未授权数据集，单表/多表统一校验；仅 JSONB 旧路径使用）
        self._allowed_dataset_ids = {str(ds.id).lower() for ds in self.datasets}
        # DuckDB 方言开关（query() 入口按物化状态决定；存量回退 JSONB）
        self._use_duckdb = False
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_API_BASE,
        )
        self._current_question: str = ''  # query() 入口写入，供 _get_few_shot_cases 生成向量

    def _prepare_engine(self) -> None:
        """按物化状态选执行引擎：全部参与数据集已物化 → DuckDB 联邦，
        否则回退 JSONB 旧路径（惰性物化失败/存量数据集）。"""
        from apps.datasets.services.materialize import ensure_materialized
        self._use_duckdb = all(
            ensure_materialized(ds) for ds in self.datasets)

    # ===== Schema 发现 =====

    def _discover_schema(self) -> dict:
        from apps.datasets.services.analyzer import (
            get_schema_summary, get_multi_schema_summary,
        )
        # business_description 独立注入（不拼进 schema_summary）：
        # 1) 让 LLM 区分"数据分布"和"业务语义" 2) 改业务文档不影响 schema 缓存命中
        if self.is_multi:
            # 多数据集：业务说明按别名分列，让 LLM 知道哪段说明对应哪个别名
            from apps.datasets.services.analyzer import _MULTI_ALIASES
            desc_lines = []
            for alias, ds in zip(_MULTI_ALIASES, self.datasets):
                d = ds.business_description.strip() or '无'
                desc_lines.append(f'{alias} "{ds.name}": {d}')
            business_description = '\n'.join(desc_lines)
            schema_summary = get_multi_schema_summary(self.datasets)
        else:
            business_description = self.dataset.business_description.strip() or '无'
            schema_summary = get_schema_summary(self.dataset)
        return {
            'schema_summary': schema_summary,
            'few_shot_cases': self._get_few_shot_cases(),
            'business_description': business_description,
        }

    def _get_few_shot_cases(self) -> str:
        """取语义最相关的 3 条历史成功查询作为 few-shot 案例。

        升级前：order_by('-created_at')[:3]——按时间倒序，可能选到语义不相关的案例
        升级后：把当前问题向量化，按余弦距离找语义最相关的 3 条
        降级策略：embedding 生成失败或该数据集无向量化的历史 → 退化为时间倒序
        """
        from apps.query.services.embedding import embed_question
        from pgvector.django import CosineDistance

        question_vec = embed_question(self._current_question) if self._current_question else None

        if question_vec is not None:
            # 语义检索：annotate 计算余弦距离，按距离升序取最近 3 条
            # 多数据集联合查询取"任一参与数据集"的历史（语义相关的自然浮出）
            base = QueryHistory.objects.filter(
                dataset__in=self.datasets,
                is_success=True,
                question_embedding__isnull=False,
            )
            if self._use_duckdb:
                # 方言隔离：排除 JSONB 时代的 data->>'col' SQL，防教坏新 prompt
                base = base.exclude(generated_sql__contains='data->>')
            cases = list(
                base
                .annotate(distance=CosineDistance('question_embedding', question_vec))
                .order_by('distance')[:3]
            )
            if cases:
                return '\n\n'.join(
                    f"问题: {c.question}\nSQL: {c.generated_sql}" for c in cases
                )
            # 该数据集还没有向量化历史，降级到时间倒序

        # 降级：embedding 失败 或 无向量化历史 → 时间倒序取 3 条
        base = QueryHistory.objects.filter(
            dataset__in=self.datasets, is_success=True
        )
        if self._use_duckdb:
            base = base.exclude(generated_sql__contains='data->>')
        cases = base.order_by('-created_at')[:3]
        if not cases:
            return '无'
        return '\n\n'.join(
            f"问题: {c.question}\nSQL: {c.generated_sql}" for c in cases
        )

    # ===== SQL 安全（委托模块级公共函数，外部数据源路径复用同一套校验）=====

    @staticmethod
    def _strip_sql_comments(sql: str) -> str:
        return strip_sql_comments(sql)

    def _validate_sql(self, sql: str) -> bool:
        """只读 SQL 校验（见模块级 validate_select_sql）。

        DuckDB 路径连接层即隔离（只挂载参与数据集文件），不做 uuid 白名单；
        JSONB 旧路径保留白名单防 LLM 幻觉引用未授权数据集。
        """
        if self._use_duckdb:
            return validate_select_sql(sql)
        return validate_select_sql(sql, self._allowed_dataset_ids)

    def _add_limit(self, sql: str) -> str:
        return add_limit_clause(sql, 1000)

    def _clean_sql(self, sql: str) -> str:
        return clean_sql(sql)

    # ===== SQL 生成 =====

    @staticmethod
    def _escape_braces(text: str) -> str:
        """转义花括号，避免 ChatPromptTemplate 误解析 JSON"""
        return text.replace('{', '{{').replace('}', '}}')

    def _generate_sql(self, question: str, schema_info: dict) -> str:
        if self._use_duckdb:
            generate_template = (
                SQL_GENERATE_MULTI_SYSTEM if self.is_multi else SQL_GENERATE_SYSTEM
            )
        else:
            generate_template = (
                SQL_GENERATE_MULTI_LEGACY_SYSTEM if self.is_multi
                else SQL_GENERATE_LEGACY_SYSTEM
            )
        prompt = ChatPromptTemplate.from_messages([
            ('system', self._escape_braces(generate_template.safe_substitute(
                schema_summary=schema_info['schema_summary'],
                few_shot_cases=schema_info['few_shot_cases'],
                dataset_id=str(self.dataset.id),
                business_description=schema_info.get('business_description', '无'),
            ))),
            ('human', self._escape_braces(SQL_GENERATE_USER.safe_substitute(
                question=question,
            ))),
        ])
        chain = prompt | self.llm
        response = chain.invoke({})
        return self._clean_sql(response.content)

    def _regenerate_sql(self, question: str, failed_sql: str,
                        error_msg: str, schema_info: dict) -> str:
        fix_template = SQL_FIX_MULTI_SYSTEM if self.is_multi else SQL_FIX_SYSTEM
        prompt = ChatPromptTemplate.from_messages([
            ('system', self._escape_braces(fix_template.safe_substitute(
                schema_summary=schema_info['schema_summary'],
            ))),
            ('human', self._escape_braces(SQL_FIX_USER.safe_substitute(
                question=question,
                failed_sql=failed_sql,
                error_msg=error_msg,
            ))),
        ])
        chain = prompt | self.llm
        response = chain.invoke({})
        return self._clean_sql(response.content)

    # ===== SQL 执行 =====

    def _execute_sql(self, sql: str) -> tuple:
        """执行 SQL，返回 (净化后的 rows, 列类型映射)。

        DuckDB 路径：单表走只读文件连接，多表走 ATTACH 联邦；
        JSONB 旧路径：Django cursor（平台 PG）。
        列类型在 sanitize 前推断——_sanitize_for_json 会把 Decimal→float、
        datetime→ISO 字符串，类型信息丢失后再推断不准。
        """
        if self._use_duckdb:
            if self.is_multi:
                return execute_duckdb_multi_sql(self.datasets, sql)
            return execute_duckdb_sql(self.dataset, sql)
        return execute_select_sql(sql, infer_types=True)

    # ===== 主流程 =====

    def query(self, question: str) -> dict:
        start_time = time.time()
        self._current_question = question  # 供 _get_few_shot_cases 生成 embedding

        # 0. 引擎选择（惰性物化；失败回退 JSONB 旧路径）
        self._prepare_engine()

        # 1. Schema发现
        schema_info = self._discover_schema()

        # 2. SQL生成
        sql = self._generate_sql(question, schema_info)

        # 3. 安全审查
        if not self._validate_sql(sql):
            elapsed = int((time.time() - start_time) * 1000)
            return {
                'error': '生成的SQL包含不允许的操作，仅支持SELECT查询',
                'sql': sql,
                'success': False,
                'retry_count': 0,
                'execution_time_ms': elapsed,
            }

        # 4. 自动加LIMIT
        sql = self._add_limit(sql)

        # 5. SQL执行 + 自动重试
        retry_count = 0
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                results, column_types = self._execute_sql(sql)
                elapsed = int((time.time() - start_time) * 1000)
                return {
                    'sql': sql,
                    'success': True,
                    'retry_count': retry_count,
                    'execution_time_ms': elapsed,
                    'data': results,
                    'row_count': len(results),
                    'column_types': column_types,
                }
            except Exception as e:
                retry_count += 1
                logger.warning(
                    "SQL执行失败 (尝试 %d/%d): %s",
                    retry_count, self.MAX_RETRIES, e,
                )
                if attempt < self.MAX_RETRIES:
                    sql = self._regenerate_sql(
                        question, sql, str(e), schema_info
                    )
                    if not self._validate_sql(sql):
                        elapsed = int((time.time() - start_time) * 1000)
                        return {
                            'error': '修复后的SQL仍包含不允许的操作',
                            'sql': sql,
                            'success': False,
                            'retry_count': retry_count,
                            'execution_time_ms': elapsed,
                        }
                    sql = self._add_limit(sql)
                else:
                    elapsed = int((time.time() - start_time) * 1000)
                    return {
                        'sql': sql,
                        'error': str(e),
                        'success': False,
                        'retry_count': retry_count,
                        'execution_time_ms': elapsed,
                    }
