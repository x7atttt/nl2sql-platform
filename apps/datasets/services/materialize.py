# -*- coding: utf-8 -*-
"""文件数据集物化：CSV/Excel/JSON/Parquet → DuckDB 本地文件（每数据集一个）。

并发纪律（DuckDB 官方语义：一个进程读写 或 多进程只读，不可并存）：
- 写入只发生在上传解析/惰性迁移时（单写者，Redis 锁互斥）
- 查询一律 read_only=True 短连接（多进程/多 worker 并发安全）
- 删数据集 = 删文件，天然生命周期绑定，无孤儿表

表结构：单表 data，列类型由 DataFrame 自动推断（int64→BIGINT / float64→DOUBLE /
object→VARCHAR），列名沿用 clean_dataframe 的规范化结果（可含中文，SQL 引用需双引号）。
"""
import logging
import os
import time
import uuid
from contextlib import contextmanager

import duckdb
import pandas as pd

from django.conf import settings

from apps.query.services.trace import span

logger = logging.getLogger(__name__)

_TABLE = 'data'


def duckdb_path(dataset) -> str:
    """数据集的 .duckdb 文件路径（由 dataset.id 派生，确定性、无碰撞）。"""
    return str(settings.DUCKDB_DATA_DIR / f'ds_{dataset.id.hex[:12]}.duckdb')


def is_materialized(dataset) -> bool:
    return os.path.exists(duckdb_path(dataset))


@contextmanager
def connect_readonly(dataset):
    """只读短连接（查询路径唯一打开方式；文件不存在抛 FileNotFoundError）。"""
    path = duckdb_path(dataset)
    if not os.path.exists(path):
        raise FileNotFoundError(f'数据集未物化: {path}')
    con = duckdb.connect(path, read_only=True)
    try:
        yield con
    finally:
        con.close()


def _write_connect(dataset):
    """写连接（上传/迁移路径专用，配合 Redis 锁保证单写者）。"""
    settings.DUCKDB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(duckdb_path(dataset))


def create_table_from_df(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                         table: str = _TABLE) -> None:
    """DataFrame → 建表（CTAS，类型自动推断）。空 DataFrame 建空表。"""
    con.register('df_view', df)
    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM df_view')
    con.unregister('df_view')


def append_df(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
              table: str = _TABLE) -> None:
    """DataFrame 追加进已存在的表（分块物化路径用）。"""
    con.register('df_chunk', df)
    con.execute(f'INSERT INTO "{table}" SELECT * FROM df_chunk')
    con.unregister('df_chunk')


def materialize_dataset(dataset, df: pd.DataFrame | None = None) -> str:
    """整文件一次性物化（同步上传路径）。返回 db 文件路径。

    df 传 None 时从 media 原文件读取（惰性迁移路径）；
    上传路径传入已清洗的 DataFrame 避免重复解析。
    失败时删除半成品文件并抛出原异常（不留损坏的库文件）。
    """
    if df is None:
        from apps.datasets.services.parser import _read_file, clean_dataframe
        df = clean_dataframe(_read_file(dataset.file.path, dataset.file_name))
    con = _write_connect(dataset)
    try:
        create_table_from_df(con, df)
    except Exception:
        con.close()
        try:
            os.remove(duckdb_path(dataset))
        except OSError:
            pass
        raise
    con.close()
    return duckdb_path(dataset)


def delete_duckdb(dataset) -> None:
    """删除物化文件（幂等）。"""
    try:
        os.remove(duckdb_path(dataset))
    except FileNotFoundError:
        pass


def ensure_materialized(dataset, trace_id: str | None = None,
                        timeout_s: float = 30.0) -> bool:
    """惰性物化：未物化的存量数据集（DataRow 时代）从 media 原文件迁移。

    Returns:
        True = 已物化（含本来就存在）；False = 物化失败
        （media 原文件丢失/解析失败，调用方回退 JSONB 旧路径）
    并发：Redis SETNX 锁互斥；抢不到锁的进程等文件出现（等不到按失败回退）。
    """
    if is_materialized(dataset):
        return True
    if not dataset.file or not os.path.exists(dataset.file.path):
        return False

    import redis as redis_lib
    client = redis_lib.from_url(settings.REDIS_URL)
    lock_key = f'materialize:{dataset.id}'
    got_lock = False
    try:
        got_lock = bool(client.set(lock_key, '1', nx=True, ex=120))
        if not got_lock:
            # 别的进程/请求正在物化：等它完成
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if is_materialized(dataset):
                    return True
                time.sleep(0.5)
            return False
        with span(trace_id, 'materialize', '存量数据集惰性物化',
                  dataset=str(dataset.id)):
            materialize_dataset(dataset)
        return is_materialized(dataset)
    except Exception:
        logger.warning('惰性物化失败 %s，调用方将回退旧路径', dataset.id,
                       exc_info=True)
        return False
    finally:
        if got_lock:
            try:
                client.delete(lock_key)
            except Exception:
                pass
