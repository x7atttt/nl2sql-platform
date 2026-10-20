import io

import pandas as pd

from apps.query.services.nl2sql import (
    execute_select_sql, execute_duckdb_sql, execute_duckdb_multi_sql, _HAS_LIMIT_RE,
)


class ExportService:
    """数据导出服务

    根据 QueryHistory 中记录的 SQL 重新执行查询，导出为 CSV/Excel。
    不持久化查询结果，避免存储大量数据。
    """

    @staticmethod
    def execute_query(history) -> list:
        """按历史记录的执行引擎重新执行 SQL，返回结果列表。

        duckdb（物化数据集）走只读文件连接；platform-pg（JSONB 旧路径）
        走 Django cursor。自动补 LIMIT 1000（词边界判断防子串误判）。
        外部源记录不走此方法（UI 导出禁用，重跑由 rerun 视图单独处理）。
        """
        sql = history.generated_sql
        if not _HAS_LIMIT_RE.search(sql):
            sql = sql.rstrip(';') + ' LIMIT 1000'
        if history.execution_engine == 'duckdb':
            multi = list(history.datasets.all())
            if multi:
                data, _column_types = execute_duckdb_multi_sql(multi, sql)
            else:
                data, _column_types = execute_duckdb_sql(history.dataset, sql)
            return data
        return execute_select_sql(sql, infer_types=False)

    @staticmethod
    def export_csv(data: list) -> bytes:
        df = pd.DataFrame(data)
        return df.to_csv(index=False).encode('utf-8-sig')

    @staticmethod
    def export_excel(data: list) -> bytes:
        df = pd.DataFrame(data)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='查询结果')
        return buffer.getvalue()
