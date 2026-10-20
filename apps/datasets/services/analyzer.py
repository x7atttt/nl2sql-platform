import json
import logging

import pandas as pd
import redis
from django.conf import settings

from apps.datasets.models import Dataset, DataRow

logger = logging.getLogger(__name__)

MAX_ROWS = 50000
_TOP_VALUE_MAX_LEN = 50  # 高频值展示截断长度（URL/长描述等单值可达数千字符）


def _truncate_value(val: str, max_len: int = _TOP_VALUE_MAX_LEN) -> str:
    """截断超长高频值，前端表格展示用。

    URL/长描述/嵌套 JSON 等单值最长可达数千字符，原样返回会撑爆表格单元格。
    截断后加省略号标记，前端 tooltip 仍可展示完整值的"前缀"足够区分。
    """
    if len(val) <= max_len:
        return val
    return val[:max_len] + '...'

# schema 缓存：项目是"上传快照"模式，数据集不变则 schema 也不变。
# 用现有 Redis 连接（复用 db1，不分库），按 key 前缀 schema:{dataset_id} 逻辑隔离。
# 数据集删除/分享变更时主动失效（见 invalidate_schema_cache）。
_SCHEMA_CACHE_TTL = 60 * 60 * 24 * 7  # 7 天兜底（理论上永久，加 TTL 防止意外残留）


_cache_client: redis.Redis | None = None


def _get_cache_client() -> redis.Redis:
    """全局单例 Redis 客户端（惰性创建，复用连接池，避免每次 from_url 新建连接）。"""
    global _cache_client
    if _cache_client is None:
        _cache_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _cache_client


def _cache_key(dataset_id) -> str:
    return f'schema:{dataset_id}'


def invalidate_schema_cache(dataset_id) -> None:
    """数据集变更时主动失效 schema 缓存。

    调用时机：Dataset 删除、DataRow 大规模变更（重新解析）。
    DatasetShare 变更不影响 schema（分享是授权不是数据变化），无需调。
    同时清单表摘要缓存和多表构件缓存（schema_parts，联合查询用）。
    """
    try:
        _get_cache_client().delete(_cache_key(dataset_id), f'schema_parts:{dataset_id}')
    except Exception:
        # 缓存失效失败不阻塞主流程（最坏情况是读到旧缓存，TTL 7 天兜底）
        logger.warning('invalidate_schema_cache failed for %s', dataset_id)


def _load_dataframe(dataset: Dataset, max_rows: int = MAX_ROWS) -> dict:
    """加载 Dataset 数据到 DataFrame（双路径）。

    物化数据集（新上传/已惰性迁移）：DuckDB 只读查询（引擎内截断，快）；
    存量数据集（DataRow JSONB 时代且未迁移）：沿用 ORM 迭代读取。
    Returns:
        {'df': DataFrame, 'types': dict, 'total_rows': int, 'sampled': bool}
    """
    from apps.datasets.services.materialize import connect_readonly
    try:
        with connect_readonly(dataset) as con:
            df = con.execute(
                f'SELECT * FROM data LIMIT {int(max_rows)}'
            ).df()
            total_rows = con.execute('SELECT COUNT(*) FROM data').fetchone()[0]
        # duckdb 列名恒为字符串；None 统一为 NaN 供下方统计逻辑处理
        df = df.where(pd.notnull(df), None)
    except FileNotFoundError:
        return _load_dataframe_legacy(dataset, max_rows)

    return {
        'df': df,
        'types': _classify_columns(df),
        'total_rows': total_rows,
        'sampled': total_rows > max_rows,
    }


def _load_dataframe_legacy(dataset: Dataset, max_rows: int = MAX_ROWS) -> dict:
    """存量 JSONB 路径加载（DataRow 未迁移的数据集）。"""
    rows = []
    total_rows = 0
    for data in (
        DataRow.objects.filter(dataset=dataset)
        .order_by('row_index')
        .values_list('data', flat=True)
        .iterator(chunk_size=1000)
    ):
        if total_rows >= max_rows:
            break
        rows.append(data)
        total_rows += 1

    actual_count = DataRow.objects.filter(dataset=dataset).count()
    sampled = actual_count > max_rows

    if not rows:
        return {
            'df': pd.DataFrame(),
            'types': {},
            'total_rows': 0,
            'sampled': False,
        }

    df = pd.DataFrame(rows)
    return {
        'df': df,
        'types': _classify_columns(df),
        'total_rows': actual_count,
        'sampled': sampled,
    }


def _classify_columns(df: pd.DataFrame) -> dict:
    """推断每列的数据类型"""
    types = {}
    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            types[col] = 'text'
            continue

        sample = series.head(100)
        has_bool = any(isinstance(v, bool) for v in sample)
        has_str = any(isinstance(v, str) for v in sample)

        if has_bool and not has_str:
            types[col] = 'boolean'
        elif has_str:
            types[col] = 'text'
        elif all(isinstance(v, int) for v in sample):
            types[col] = 'integer'
        else:
            types[col] = 'numeric'
    return types


def get_column_stats(dataset: Dataset, loaded: dict | None = None) -> dict:
    """每列统计信息,给前端表格渲染。

    可选 loaded 参数：传入已加载的 _load_dataframe 结果，避免与
    get_dataset_overview 在同一请求里重复加载（50000 行 × 2 次→1 次）。
    """
    if dataset.status != 'completed':
        return {'columns': [], 'total_rows': 0, 'sampled': False}

    if loaded is None:
        loaded = _load_dataframe(dataset)
    df = loaded['df']
    types = loaded['types']

    if df.empty:
        return {
            'columns': [],
            'total_rows': 0,
            'sampled': False,
        }

    columns = []
    for col in df.columns:
        series = df[col]
        col_type = types.get(col, 'text')
        null_count = int(series.isna().sum())
        distinct_count = int(series.nunique())

        stats = {'null_count': null_count, 'distinct_count': distinct_count}

        if col_type in ('integer', 'numeric'):
            clean = pd.to_numeric(series, errors='coerce').dropna()
            if len(clean) > 0:
                stats['min'] = round(float(clean.min()), 2)
                stats['max'] = round(float(clean.max()), 2)
                stats['avg'] = round(float(clean.mean()), 2)
                stats['median'] = round(float(clean.median()), 2)
        elif col_type in ('text', 'boolean'):
            top = series.value_counts().head(10)
            # 超长值截断（如 URL/长描述，单值最长可达数千字符，前端表格塞不下）
            stats['top_values'] = [
                {'value': _truncate_value(str(v)), 'count': int(c)}
                for v, c in top.items()
            ]

        columns.append({
            'name': col,
            'type': col_type,
            **stats,
        })

    return {
        'columns': columns,
        'total_rows': loaded['total_rows'],
        'sampled': loaded['sampled'],
    }


def _compute_schema_parts(dataset: Dataset) -> dict:
    """一次加载数据，产出 schema 摘要的两类构件（无缓存）。

    Returns:
        {'body': str, 'text_tops': {col: [top values]}}
        - body: 列统计 + 样本行文本（不含表头），单表/多表摘要共用
        - text_tops: 低基数文本列的 top 值列表，供多表"疑似关联列"预检
    """
    loaded = _load_dataframe(dataset)
    df = loaded['df']
    types = loaded['types']

    if df.empty:
        return {'body': '数据集为空', 'text_tops': {}, 'total_rows': loaded['total_rows']}

    lines = []
    text_tops = {}

    for col in df.columns:
        col_type = types.get(col, 'text')
        series = df[col]
        distinct_count = int(series.nunique())

        if col_type in ('integer', 'numeric'):
            clean = pd.to_numeric(series, errors='coerce').dropna()
            if len(clean) > 0:
                lines.append(
                    f'  - {col} ({col_type}): '
                    f'min={round(float(clean.min()), 2)}, '
                    f'max={round(float(clean.max()), 2)}, '
                    f'avg={round(float(clean.mean()), 2)}, '
                    f'{distinct_count} distinct'
                )
            else:
                lines.append(f'  - {col} ({col_type}): all null')
        elif col_type == 'boolean':
            top = series.value_counts().head(2)
            parts = [f'{v}={int(c)}' for v, c in top.items()]
            lines.append(f'  - {col} ({col_type}): {", ".join(parts)}')
        else:
            # 文本列：高基数列（distinct 接近总行数，如 url/image_urls/description，
            # 每行都不同）不注入 top 5——这些列的 top 5 是随机的 5 个长 URL/描述，
            # 对 SQL 生成零价值，却让 schema_summary 膨胀到 13K+ 字符拖慢 LLM。
            total = len(series)
            is_high_cardinality = total > 0 and distinct_count / total >= 0.9
            top_vals = series.dropna().value_counts().head(5)
            if is_high_cardinality:
                lines.append(
                    f'  - {col} ({col_type}): {distinct_count} distinct'
                )
            else:
                # 截断超长值（URL/长描述塞进 prompt 既费 token 又干扰 LLM）
                top_str = ', '.join(_truncate_value(str(v)) for v in top_vals.index)
                lines.append(
                    f'  - {col} ({col_type}): {distinct_count} distinct, top: {top_str}'
                )
            # 原始 top 值（截断前）无条件记录，供多表关联列预检比对值重叠——
            # 高基数列（order_id/url 等唯一键）恰是最常见的 JOIN 键，不能排除；
            # 该数据只用于重叠检测（命中才输出共同值摘要），不进 prompt 正文，
            # 不影响上面的体积控制。
            text_tops[col] = [str(v) for v in top_vals.index]

    lines.append('')
    lines.append('Sample rows:')
    # 截断每行 JSON 长度：电商等数据集每行可能含 url/image_urls 等长字段，
    # 3 行完整 JSON 可达数 KB，截断到 300 字符避免 prompt 膨胀
    for _, row in df.head(3).iterrows():
        row_json = json.dumps(row.to_dict(), ensure_ascii=False, default=str)
        if len(row_json) > 300:
            row_json = row_json[:300] + '...'
        lines.append('  ' + row_json)

    if loaded['sampled']:
        lines.append('')
        lines.append(
            f'(Note: stats based on {len(df)} row sample of {loaded["total_rows"]} total)'
        )

    return {'body': '\n'.join(lines), 'text_tops': text_tops,
            'total_rows': loaded['total_rows']}


def get_schema_summary(dataset: Dataset) -> str:
    """生成结构化 schema 摘要，供 NL2SQL prompt 注入。

    带 Redis 缓存：项目是"上传快照"模式，数据集不变则 schema 也不变，
    重复计算是纯浪费。第一次算完缓存，后续查询命中缓存省 90%+ 成本。
    数据集删除/重新解析时调 invalidate_schema_cache 主动失效。
    """
    if dataset.status != 'completed':
        return '数据集尚未处理完成'

    # 读缓存
    cache_key = _cache_key(dataset.id)
    try:
        cached = _get_cache_client().get(cache_key)
        if cached:
            return cached
    except Exception:
        # Redis 不可用不阻塞主流程，降级为直接计算（和无缓存时一样）
        logger.warning('schema cache read failed for %s, fallback to compute', dataset.id)

    loaded_rows_hint = dataset.row_count
    parts = _compute_schema_parts(dataset)
    if parts['body'] == '数据集为空':
        return '数据集为空'
    from apps.datasets.services.materialize import is_materialized
    if is_materialized(dataset):
        header = (f'Table: data (共 {parts["total_rows"]} 行，DuckDB 物化表，'
                  f'列有真实类型，中文/特殊列名用双引号引用)')
    else:
        header = f'Table: dataset_rows (共 {parts["total_rows"]} 行)'
    result = (
        f'{header}\n\n'
        f'Columns:\n{parts["body"]}'
    )

    # 写缓存（数据集不变则 schema 不变，长期缓存）
    try:
        _get_cache_client().set(cache_key, result, ex=_SCHEMA_CACHE_TTL)
    except Exception:
        logger.warning('schema cache write failed for %s', dataset.id)

    return result


# ===== 多数据集联合查询 schema 摘要 =====

# 多表查询的数据集别名（prompt 中 LLM 用别名引用各数据集的行）
_MULTI_ALIASES = ['t1', 't2', 't3']


def _schema_parts_cached(dataset: Dataset) -> dict:
    """带缓存的 schema 构件（key: schema_parts:{id}，与单表摘要缓存独立）。

    单表 get_schema_summary 缓存的是拼好表头的完整文本，多表需要按
    "别名 + dataset_id" 重新组织表头，没法复用那份缓存，单独缓存构件。
    """
    cache_key = f'schema_parts:{dataset.id}'
    try:
        cached = _get_cache_client().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        logger.warning('schema_parts cache read failed for %s', dataset.id)

    parts = _compute_schema_parts(dataset)
    try:
        _get_cache_client().set(cache_key, json.dumps(parts, ensure_ascii=False),
                                ex=_SCHEMA_CACHE_TTL)
    except Exception:
        logger.warning('schema_parts cache write failed for %s', dataset.id)
    return parts


def _build_join_hints(alias_parts: dict, duckdb_mode: bool = False) -> list:
    """两两比对数据集的文本列 top 值重叠度，产出"疑似关联列"提示。

    判定标准（宽松取并集，宁可多提示让 LLM 参考）：
    - 共同值 ≥ 2 且（重叠率 ≥ 50% 或共同值 ≥ 3）
    重叠率 = 共同值数 / 较小一方的 top 值数
    列引用格式随执行引擎：DuckDB 用 别名."列"，JSONB 旧路径用 别名.data->>'列'。
    """
    hints = []
    aliases = list(alias_parts)
    for i in range(len(aliases)):
        for j in range(i + 1, len(aliases)):
            a, b = aliases[i], aliases[j]
            tops_a = alias_parts[a]['text_tops']
            tops_b = alias_parts[b]['text_tops']
            for col_a, vals_a in tops_a.items():
                for col_b, vals_b in tops_b.items():
                    set_a = {v.strip() for v in vals_a if v.strip()}
                    set_b = {v.strip() for v in vals_b if v.strip()}
                    common = set_a & set_b
                    if len(common) < 2:
                        continue
                    smaller = min(len(set_a), len(set_b)) or 1
                    if len(common) / smaller >= 0.5 or len(common) >= 3:
                        preview = ', '.join(sorted(common)[:5])
                        if duckdb_mode:
                            ref_a, ref_b = f'{a}."{col_a}"', f'{b}."{col_b}"'
                        else:
                            ref_a, ref_b = f"{a}.data->>'{col_a}'", f"{b}.data->>'{col_b}'"
                        hints.append(
                            f'  {ref_a} ≈ {ref_b}（共同值: {preview}）'
                        )
    return hints


def get_multi_schema_summary(datasets: list) -> str:
    """生成多数据集联合 schema 摘要，供联合查询 prompt 注入。

    结构：每个数据集一段（别名 + 表引用 + 列统计）+ 疑似关联列提示。
    表引用随执行引擎：全部物化时用 DuckDB 联邦表 t{n}.data（NL2SQLService
    按同一条件选引擎），否则用 dataset_rows + dataset_id 过滤（旧路径）。
    """
    from apps.datasets.services.materialize import is_materialized
    duckdb_mode = all(is_materialized(ds) for ds in datasets)

    sections = []
    alias_parts = {}
    for alias, ds in zip(_MULTI_ALIASES, datasets):
        parts = _schema_parts_cached(ds)
        if duckdb_mode:
            head = (f'数据集 "{ds.name}" (表 {alias}.data，引用写法 FROM {alias}.data {alias}，'
                    f'共 {parts["total_rows"]} 行)')
        else:
            head = (f"数据集 \"{ds.name}\" (别名 {alias}, dataset_id='{ds.id}', "
                    f"共 {parts['total_rows']} 行)")
        sections.append(f'{head}\nColumns:\n{parts["body"]}')
        alias_parts[alias] = parts

    hints = _build_join_hints(alias_parts, duckdb_mode)
    if hints:
        sections.append(
            '疑似关联列（值分布高度重叠，JOIN 时优先使用这些列做关联条件）:\n'
            + '\n'.join(hints)
        )
    else:
        sections.append(
            '（未发现明显关联列：未检测到值分布重叠的列对。'
            '如问题确需多数据集关联，请根据列语义自行判断 JOIN 条件）'
        )
    return '\n\n'.join(sections)


def get_dataset_overview(dataset: Dataset, loaded: dict | None = None) -> dict:
    """数据集概览。

    可选 loaded 参数：传入已加载的 _load_dataframe 结果，避免与
    get_column_stats 在同一请求里重复加载（50000 行 × 2 次→1 次）。
    """
    if dataset.status != 'completed':
        return {
            'row_count': 0,
            'column_count': 0,
            'columns': [],
            'status': dataset.status,
            'sampled': False,
        }

    if loaded is None:
        loaded = _load_dataframe(dataset)
    df = loaded['df']

    if df.empty:
        return {
            'row_count': dataset.row_count,
            'column_count': dataset.column_count,
            'columns': [],
            'status': dataset.status,
            'null_summary': {},
            'sampled': False,
        }

    memory_mb = round(df.memory_usage(deep=True).sum() / (1024 * 1024), 2)
    if loaded['sampled']:
        memory_mb = round(memory_mb * dataset.row_count / len(df), 2)

    return {
        'row_count': dataset.row_count,
        'column_count': dataset.column_count,
        'columns': list(df.columns),
        'status': dataset.status,
        'memory_estimate_mb': memory_mb,
        'null_summary': {
            col: int(df[col].isna().sum()) for col in df.columns
        },
        'sampled': loaded['sampled'],
    }
