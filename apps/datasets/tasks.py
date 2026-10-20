from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=0,
    acks_late=True,
)
def process_large_file(self, dataset_id: str):
    """异步处理大文件（>=10MB）：分块清洗后物化为 DuckDB 文件。

    指数退避重试：2^n 秒（1→2→4→8→16），最多5次。
    超过5次标记为 failed（死信队列），Admin 后台可见。
    """
    from apps.datasets.models import Dataset
    from apps.datasets.services.parser import (
        clean_dataframe, validate_dataframe_size, DatasetTooLargeError,
        MAX_ROWS_PER_DATASET,
    )
    from apps.datasets.services.materialize import (
        create_table_from_df, append_df, delete_duckdb,
    )
    import duckdb as duckdb_lib
    import pandas as pd

    con = None
    try:
        dataset = Dataset.objects.get(id=dataset_id)
        dataset.status = 'processing'
        dataset.save(update_fields=['status', 'updated_at'])

        # 重试可能留下半成品文件，先清（duckdb 库文件损坏会让重试必败）
        delete_duckdb(dataset)

        chunk_size = 10000
        total_rows = 0
        file_path = dataset.file.path

        if dataset.file_name.endswith('.csv'):
            reader = pd.read_csv(file_path, chunksize=chunk_size)
        else:
            df = pd.read_excel(file_path)
            reader = [df.iloc[i:i + chunk_size] for i in range(0, len(df), chunk_size)]

        for chunk_df in reader:
            chunk_df = clean_dataframe(chunk_df)

            # 规模校验：列数（首个 chunk 即可判断）+ 累计行数
            if total_rows == 0:
                validate_dataframe_size(chunk_df)
            elif total_rows + len(chunk_df) > MAX_ROWS_PER_DATASET:
                raise DatasetTooLargeError(
                    f'数据集行数超过上限 {MAX_ROWS_PER_DATASET} 行，'
                    f'请拆分或筛选后上传'
                )

            if con is None:
                # 首块：建表（类型推断）；后续块：追加。单连接贯穿全部分块
                from apps.datasets.services.materialize import _write_connect
                con = _write_connect(dataset)
                create_table_from_df(con, chunk_df)
            else:
                append_df(con, chunk_df)

            total_rows += len(chunk_df)
            _send_progress(dataset_id, total_rows)
        con.close()
        con = None

        dataset.row_count = total_rows
        dataset.column_count = len(chunk_df.columns)
        dataset.status = 'completed'
        dataset.save(update_fields=['row_count', 'column_count', 'status', 'updated_at'])
        _send_progress(dataset_id, total_rows, status='completed')

        # 处理完成 → 异步生成推荐查询（不阻塞进度推送，LLM 7 秒）
        generate_suggested_questions.delay(str(dataset.id))

    except DatasetTooLargeError as exc:
        # 超限是不可恢复的，重试也无意义，直接清理 + 通知前端
        logger.error(f'数据集 {dataset_id} 超限: {exc}')
        try:
            dataset = Dataset.objects.get(id=dataset_id)
            from apps.datasets.services.parser import delete_dataset_completely
            delete_dataset_completely(dataset)
        except Dataset.DoesNotExist:
            pass
        _send_progress(dataset_id, 0, status='failed')

    except Exception as exc:
        logger.error(f'处理数据集 {dataset_id} 失败: {exc}')
        # 清理半成品物化文件，避免损坏的库文件阻塞重试
        try:
            dataset = Dataset.objects.get(id=dataset_id)
            delete_duckdb(dataset)
        except Dataset.DoesNotExist:
            return

        if self.request.retries < self.max_retries:
            countdown = 2 ** self.request.retries
            logger.info(f'重试 {self.request.retries + 1}/{self.max_retries}，等待 {countdown}秒')
            raise self.retry(exc=exc, countdown=countdown)
        else:
            dataset.status = 'failed'
            dataset.save(update_fields=['status', 'updated_at'])
            _send_progress(dataset_id, 0, status='failed')
            logger.error(f'数据集 {dataset_id} 重试{self.max_retries}次后仍然失败，进入死信队列')
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def _send_progress(dataset_id: str, total_rows: int, status: str = 'processing'):
    """通过 WebSocket 推送处理进度/终态到前端。

    status 三种取值：
    - 'processing'：处理中，每 chunk 推一次（progress=已处理行数）
    - 'completed'：处理完成，任务结束时推一次（前端据此关闭连接）
    - 'failed'：处理失败，重试耗尽时推一次
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        message = {
            'processing': f'已处理 {total_rows} 行',
            'completed': f'处理完成，共 {total_rows} 行',
            'failed': '处理失败',
        }.get(status, f'已处理 {total_rows} 行')

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'dataset_{dataset_id}',
            {
                'type': 'progress_update',
                'progress': total_rows,
                'status': status,
                'message': message,
            },
        )
    except Exception:
        pass


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def generate_suggested_questions(self, dataset_id: str):
    """异步生成推荐查询（数据集处理完成后触发）。

    LLM 看 schema 摘要 + 业务说明生成 4 条推荐问题，缓存到
    Dataset.suggested_questions。二次进入详情页读缓存不重算。
    失败不阻塞数据集使用（推荐是锦上添花）。
    """
    from apps.datasets.models import Dataset
    from apps.datasets.services.analyzer import get_schema_summary
    from apps.query.services.question_advisor import generate_suggested_questions as gen_qs

    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
        return

    # 已生成过则跳过（避免重复消耗 LLM）
    if dataset.suggested_questions:
        return

    # 数据集必须已完成处理才能生成 schema 摘要
    if dataset.status != 'completed':
        return

    try:
        schema_summary = get_schema_summary(dataset)
        questions = gen_qs(
            dataset_name=dataset.name,
            schema_summary=schema_summary,
            business_description=dataset.business_description,
        )
        if questions:
            dataset.suggested_questions = questions
            dataset.save(update_fields=['suggested_questions', 'updated_at'])
            logger.info(f'数据集 {dataset_id} 生成 {len(questions)} 条推荐查询')
    except Exception as exc:
        logger.warning(f'生成推荐查询失败 {dataset_id}: {exc}')
        # 推荐失败不值得重试（通常是 LLM 问题），静默放弃
        # 用户仍可正常查询，只是没有推荐卡片
