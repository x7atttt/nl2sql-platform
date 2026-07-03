import io

import pandas as pd

from apps.query.services.nl2sql import execute_select_sql, _HAS_LIMIT_RE


class ExportService:
    """数据导出服务

    根据 QueryHistory 中记录的 SQL 重新执行查询，导出为 CSV/Excel。
    不持久化查询结果，避免存储大量数据。
    """

    @staticmethod
    def execute_query(sql: str) -> list:
        """重新执行历史查询 SQL，返回结果列表。

        复用 execute_select_sql（与 NL2SQL 主查询共用执行+净化逻辑）。
        自动补 LIMIT 1000（用正则词边界判断，避免 'PRELIMITED' 等子串误判）。
        """
        if not _HAS_LIMIT_RE.search(sql):
            sql = sql.rstrip(';') + ' LIMIT 1000'
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
