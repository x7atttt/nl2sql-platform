# -*- coding: utf-8 -*-
"""外部数据源 schema 内省：表/列/注释/外键 + 采样列统计，供 NL2SQL prompt 注入。

与 analyzer（文件数据集）的对应关系：
- 文件数据集：DataRow JSONB → pandas 统计 → schema 摘要
- 外部数据源：inspector 内省 + 每表采样 100 行 → 同风格的 schema 摘要

真实数据库的优势：外键关系是权威的 JOIN 提示（文件路径靠"疑似关联列"猜测）。
结果 Redis 缓存 per source（TTL 7 天 + 手动失效），表结构不常变。
"""
import json
import logging

import pandas as pd
import redis
from sqlalchemy import inspect, text

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_TABLES_IN_PROMPT = 20   # 超出要求请求方显式指定表清单
_SAMPLE_ROWS = 100
_TABLES_CACHE_TTL = 60 * 60 * 24 * 7
_TRUNCATE_LEN = 50

_cache_client: redis.Redis | None = None


def _get_cache_client() -> redis.Redis:
    global _cache_client
    if _cache_client is None:
        _cache_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _cache_client


def _cache_key(source_id) -> str:
    return f'ds_tables:{source_id}'


def invalidate_tables_cache(source_id) -> None:
    try:
        _get_cache_client().delete(_cache_key(source_id))
    except Exception:
        logger.warning('invalidate_tables_cache failed for %s', source_id)


def _is_text_type(type_str: str) -> bool:
    t = (type_str or '').upper()
    return any(k in t for k in ('CHAR', 'TEXT', 'ENUM', 'UUID', 'JSON'))


def _approx_row_count(conn, db_type: str, table: str, preparer) -> int | None:
    """行数估算（便宜的近似值，供 LLM 判断"大表先聚合"）。失败返回 None。"""
    try:
        if db_type == 'postgresql':
            return conn.execute(
                text('SELECT reltuples::bigint FROM pg_class WHERE relname = :t'),
                {'t': table},
            ).scalar()
        # MySQL：information_schema 近似行数
        return conn.execute(
            text('SELECT TABLE_ROWS FROM information_schema.TABLES '
                 'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'),
            {'t': table},
        ).scalar()
    except Exception:
        return None


def _compute_tables_overview(engine, db_type: str) -> dict:
    """内省 + 采样，产出全部表的结构概览（无缓存）。"""
    insp = inspect(engine)
    preparer = engine.dialect.identifier_preparer
    tables = []
    fk_hints = []

    with engine.connect() as conn:
        for table in insp.get_table_names():
            cols_meta = insp.get_columns(table)
            columns = []
            for c in cols_meta:
                columns.append({
                    'name': c['name'],
                    'type': str(c['type']),
                    'comment': (c.get('comment') or '').strip(),
                })

            # 表注释（两方言都支持，失败静默）
            try:
                table_comment = (insp.get_table_comment(table).get('text') or '').strip()
            except Exception:
                table_comment = ''

            # 采样算文本列 top 值（供 WHERE 值匹配，同 analyzer 思路）
            text_tops = {}
            try:
                quoted = preparer.quote(table, force=True)
                rows = conn.execute(
                    text(f'SELECT * FROM {quoted} LIMIT {_SAMPLE_ROWS}')
                ).mappings().all()
                if rows:
                    df = pd.DataFrame([dict(r) for r in rows])
                    for c in columns:
                        if not _is_text_type(c['type']):
                            continue
                        series = df[c['name']].dropna().astype(str)
                        if len(series) == 0:
                            continue
                        tops = series.value_counts().head(5)
                        text_tops[c['name']] = [
                            v[:_TRUNCATE_LEN] + '...' if len(v) > _TRUNCATE_LEN else v
                            for v in tops.index
                        ]
            except Exception as e:
                logger.warning('sample table %s failed: %s', table, e)

            # 外键 → JOIN 提示
            try:
                for fk in insp.get_foreign_keys(table):
                    ref_table = fk.get('referred_table')
                    con_cols = fk.get('constrained_columns') or []
                    ref_cols = fk.get('referred_columns') or []
                    if ref_table and len(con_cols) == len(ref_cols):
                        for cc, rc in zip(con_cols, ref_cols):
                            fk_hints.append(f'{table}.{cc} = {ref_table}.{rc}')
            except Exception:
                pass

            tables.append({
                'name': table,
                'comment': table_comment,
                'row_estimate': _approx_row_count(conn, db_type, table, preparer),
                'columns': columns,
                'text_tops': text_tops,
            })

    return {'tables': tables, 'fk_hints': sorted(set(fk_hints))}


def get_tables_overview(source) -> dict:
    """带缓存的表结构概览。返回 {'tables': [...], 'fk_hints': [...]}。"""
    cache_key = _cache_key(source.id)
    try:
        cached = _get_cache_client().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        logger.warning('ds_tables cache read failed for %s', source.id)

    from apps.datasources.services.engine import create_engine_for_source
    engine = create_engine_for_source(source)
    try:
        overview = _compute_tables_overview(engine, source.db_type)
    finally:
        engine.dispose()

    try:
        _get_cache_client().set(cache_key, json.dumps(overview, ensure_ascii=False),
                                ex=_TABLES_CACHE_TTL)
    except Exception:
        logger.warning('ds_tables cache write failed for %s', source.id)
    return overview


def build_external_schema_summary(source, tables: list | None = None) -> str:
    """生成外部数据源的 schema 摘要文本（注入 NL2SQL prompt）。

    Args:
        tables: 指定表清单（表数超上限时请求方筛选后传入）；None = 全部
                （但超过 MAX_TABLES_IN_PROMPT 时抛错，调用方要求显式筛选）。
    """
    overview = get_tables_overview(source)
    all_tables = overview['tables']
    if not all_tables:
        raise ValueError('该数据源下没有可查询的表')

    if tables is None:
        if len(all_tables) > MAX_TABLES_IN_PROMPT:
            raise ValueError(
                f"该数据源有 {len(all_tables)} 张表，超过 prompt 上限 "
                f'{MAX_TABLES_IN_PROMPT} 张，请先选择要查询的表'
            )
        selected = all_tables
    else:
        wanted = set(tables)
        selected = [t for t in all_tables if t['name'] in wanted]
        missing = wanted - {t['name'] for t in selected}
        if missing:
            raise ValueError(f'表不存在：{", ".join(sorted(missing))}')

    selected_names = {t['name'] for t in selected}
    lines = [f'数据库 "{source.name}"（{source.db_type}）']

    for t in selected:
        head = f"表 {t['name']}"
        if t['row_estimate'] is not None and t['row_estimate'] >= 0:
            head += f' (约 {int(t["row_estimate"])} 行)'
        if t['comment']:
            head += f" — {t['comment']}"
        lines.append(head)
        for c in t['columns']:
            line = f"  - {c['name']} ({c['type']})"
            if c['comment']:
                line += f" — {c['comment']}"
            tops = t['text_tops'].get(c['name'])
            if tops:
                line += f": top: {', '.join(tops)}"
            lines.append(line)
        lines.append('')

    # 外键关系（只保留两侧都在本次选中表里的，避免噪声）
    relevant_fks = [
        fk for fk in overview['fk_hints']
        if all(part.split('.')[0] in selected_names for part in fk.split(' = '))
    ]
    if relevant_fks:
        lines.append('外键关系（JOIN 时优先使用这些关联条件）:')
        lines.extend(f'  {fk}' for fk in relevant_fks)

    if source.business_description.strip():
        lines.append('')
        lines.append(f"业务说明: {source.business_description.strip()}")

    return '\n'.join(lines)
