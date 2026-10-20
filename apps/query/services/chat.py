# -*- coding: utf-8 -*-
"""对话式数据查询服务（chat_file / chat_db 两个场景，流式 SSE 帧输出）。

对齐 DB-GPT 的对话形态：LLM 流式输出 thoughts → 结构化 answer/view 帧，
图表直接渲染进气泡。同时保留本项目差异化能力：只读校验 + 执行失败自动
修复重试（DB-GPT 两者皆无）。

帧协议（结构化帧；图表不内嵌 markdown 标签，前端按帧类型渲染组件）：
  delta   {"content"}                     LLM 原始输出增量（前端缓冲为思考文本）
  answer  {"thoughts","sql","chart_type"} sql 为 null 表示纯文本回答
  view    {"columns","column_types","rows","row_count"}
  error   {"message"}
  done    {"message_id","success","execution_time_ms"}
"""
import json
import logging
import time
from string import Template

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from django.conf import settings

from apps.query.models import QueryHistory, ChatMessage
from apps.query.services.nl2sql import (
    execute_select_sql, execute_duckdb_sql,
    validate_select_sql, add_limit_clause, clean_sql,
    _sanitize_for_json,
)
from apps.query.services.trace import new_trace_id, span


def _escape_braces(s: str) -> str:
    return s.replace('{', '{{').replace('}', '}}')

logger = logging.getLogger(__name__)

# 图表类型菜单（与前端 ResultChart 能力一一对应；约束 LLM 只能从菜单选）
CHART_MENU = (
    'response_table',        # 明细/单值
    'response_bar_chart',    # 分类对比
    'response_line_chart',   # 时间趋势
    'response_area_chart',   # 趋势量级
    'response_pie_chart',    # 构成占比
    'response_scatter_chart',  # 两变量相关
)

HISTORY_ROUNDS = 5   # 多轮上下文窗口（DB-GPT 用 10，数据问答 5 轮足够覆盖指代）
VIEW_ROWS_CAP = 200  # view 帧与消息 extra 的行数上限（SQL 有 LIMIT 1000 兜底）


CHAT_SYSTEM = Template("""你是一个专业的数据分析助手。根据以下信息用 SQL 回答用户问题。

$schema_summary

业务说明:
$business_description

对话上下文（最近几轮，用于理解"其中/上一个/再按"这类指代）:
$chat_history

相似查询案例（历史成功问答，参考其问法与 SQL 写法）:
$few_shot_cases

输出要求:
1. 只输出一个 JSON 对象，不要 markdown 围栏、不要多余解释，格式:
   {"thoughts": "一句话分析思路", "sql": "SELECT ...", "chart_type": "response_bar_chart"}
2. sql 只能是 SELECT 语句；问题与数据完全无关时 sql 用 null，把答案直接写在 thoughts
3. chart_type 从以下菜单选择:
   response_table(明细/单值) response_bar_chart(分类对比) response_line_chart(时间趋势)
   response_area_chart(趋势量级) response_pie_chart(构成占比) response_scatter_chart(两变量相关)

SQL 规则:
$sql_rules
""")

CHAT_FIX_SYSTEM = Template("""你是SQL修复专家。之前的输出执行或解析失败了，请根据错误信息修复。

$schema_summary

对话上下文:
$chat_history

输出要求与前次相同: 只输出一个 JSON 对象
{"thoughts": "...", "sql": "...", "chart_type": "..."}，不要围栏和解释。

SQL 规则:
$sql_rules
""")

CHAT_USER = Template('用户问题: $question\n\n请按输出要求回答:')

CHAT_FIX_USER = Template("""问题: $question

上次输出: $failed_output
错误信息: $error_msg

请修复后重新输出（只输出 JSON 对象）:""")

# chat_file：已物化数据集走 DuckDB 方言（新上传默认路径）
_DUCKDB_SQL_RULES = """- 数据已物化为 DuckDB 表 data（列有真实类型），直接用列名引用，数值列直接比较，无需类型转换
- 表名固定为 data（FROM data）；中文/特殊列名用双引号引用，如 "区域"
- 不要使用 LIMIT 以外的结果限制方式
- ORDER BY 排序时加 NULLS LAST（避免空值占满 LIMIT 结果）"""

# chat_file：存量未迁移数据集沿用 JSONB 单表方言（惰性物化失败的回退路径）
_FILE_SQL_RULES = Template("""- 数据存储在 dataset_rows 表中，每行数据在 data 字段(JSONB)里
- 文本值用 data->>'列名'，数值比较用 (data->>'列名')::numeric
- 必须包含 WHERE dataset_id = '$dataset_id' 过滤条件
- 不要使用 LIMIT 以外的结果限制方式
- ORDER BY 排序时必须加 NULLS LAST（PostgreSQL 默认 DESC 时 NULL 排最前）""")

# chat_db：真实库直接引用（规则结构与外部查询服务一致）
_EXTERNAL_SQL_RULES = Template("""- 数据存储在真实的$db_type_name数据库中，直接用 表名.列名 引用（列有真实类型，直接比较，无需类型转换）
- 跨表 JOIN 优先使用上方"外键关系"提示
- 文本列的 top 值是 WHERE 条件取值参考（照着写命中率高）
- 大表（行数多）优先 GROUP BY 聚合后再输出，避免返回明细
- 不要使用 LIMIT 以外的结果限制方式
$nulls_rule""")

_DB_TYPE_NAMES = {'mysql': 'MySQL', 'postgresql': 'PostgreSQL',
                  'sqlite': 'SQLite', 'clickhouse': 'ClickHouse'}

_NULLS_RULES = {
    'postgresql': '- ORDER BY 排序时必须加 NULLS LAST（PostgreSQL 默认 DESC 时 NULL 排最前）',
    'mysql': '- MySQL 不支持 NULLS LAST 语法；想让空值排最后用 ORDER BY (列名 IS NULL), 列名',
    'sqlite': '- ORDER BY 排序时必须加 NULLS LAST（SQLite 默认 ASC 时 NULL 排最前）',
    'clickhouse': '- ClickHouse 默认 NULL 已排在最后，且支持 ORDER BY ... NULLS LAST 语法',
}


class ChatService:
    """单会话流式查询管线。

    chat_file 走平台库（Django cursor），chat_db 走外部源 SQLAlchemy 直连；
    SQL 方言规则按场景注入。SQL 查询（含失败）写 QueryHistory（few-shot
    检索池与查询历史页持续有数据），消息落 ChatMessage。
    """

    MAX_RETRIES = 3

    def __init__(self, conversation):
        self.conversation = conversation
        self.dataset = conversation.dataset
        self.source = conversation.source
        # 本轮待处理的用户消息 id：组装上下文时排除（问题已在 human 消息里，
        # 再进 chat_history 会重复一遍）
        self._pending_user_msg_id = None
        # 本轮 trace_id（stream() 入口生成；None 时埋点跳过，供无 trace 场景直调）
        self._trace_id = None
        # chat_file 方言开关：已物化走 DuckDB，否则回退 JSONB 旧路径
        self._use_duckdb = False
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_API_BASE,
            stream_usage=True,  # 流式最后一帧带 token 用量，进 trace 属性
        )

    # ===== 上下文组装 =====

    def _schema_summary(self) -> str:
        if self.dataset:
            from apps.datasets.services.analyzer import get_schema_summary
            return get_schema_summary(self.dataset)
        from apps.datasources.services.introspect import build_external_schema_summary
        return build_external_schema_summary(self.source)

    def _sql_rules(self) -> str:
        if self.dataset:
            if self._use_duckdb:
                return _DUCKDB_SQL_RULES
            return _FILE_SQL_RULES.substitute(dataset_id=self.dataset.id)
        return _EXTERNAL_SQL_RULES.substitute(
            db_type_name=_DB_TYPE_NAMES[self.source.db_type],
            nulls_rule=_NULLS_RULES[self.source.db_type],
        )

    def _chat_history(self) -> str:
        """最近 N 轮上下文。只回传问题与 thoughts+SQL，不回传结果数据
        （结果进 prompt 只有 token 成本没有收益，DB-GPT 同款经验）。"""
        qs = ChatMessage.objects.filter(conversation=self.conversation)
        if self._pending_user_msg_id:
            qs = qs.exclude(id=self._pending_user_msg_id)
        msgs = list(qs.order_by('-round_index', '-id')[:HISTORY_ROUNDS * 2])[::-1]
        if not msgs:
            return '（首轮对话，无上下文）'
        lines = []
        for m in msgs:
            if m.role == 'user':
                lines.append(f'用户: {m.content}')
            else:
                sql = (m.extra or {}).get('sql')
                lines.append(f'助手: {m.content}' + (f'\nSQL: {sql}' if sql else ''))
        return '\n'.join(lines)

    def _few_shot_cases(self, question: str) -> str:
        """语义检索 3 条历史成功查询。按资源隔离（file 按 dataset / db 按 source），
        防跨方言 SQL 污染 prompt。降级：无向量历史 → 时间倒序 → '无'。
        """
        from pgvector.django import CosineDistance
        from apps.query.services.embedding import embed_question

        base = QueryHistory.objects.filter(is_success=True)
        if self.dataset:
            base = base.filter(dataset=self.dataset)
            if self._use_duckdb:
                # 方言隔离：排除 JSONB 时代的 data->>'col' 方言 SQL，防教坏新 prompt
                base = base.exclude(generated_sql__contains='data->>')
        else:
            base = base.filter(source=self.source)

        question_vec = None
        # 注：此 span 嵌套在 llm span 内（prompt 组装阶段），时间线按完成顺序展示
        with span(self._trace_id, 'embed', 'few-shot 问题向量化'):
            question_vec = embed_question(question) if question else None
        if question_vec is not None:
            cases = list(
                base.filter(question_embedding__isnull=False)
                .annotate(distance=CosineDistance('question_embedding', question_vec))
                .order_by('distance')[:3]
            )
            if cases:
                return self._format_cases(cases)

        cases = list(base.order_by('-created_at')[:3])
        return self._format_cases(cases) if cases else '无'

    @staticmethod
    def _format_cases(cases) -> str:
        return '\n\n'.join(f'问题: {c.question}\nSQL: {c.generated_sql}' for c in cases)

    def _build_messages(self, question: str, fix: dict | None = None) -> list:
        ctx = dict(
            schema_summary=self._schema_summary(),
            business_description=(self.dataset or self.source).business_description.strip() or '无',
            chat_history=self._chat_history(),
            few_shot_cases=self._few_shot_cases(question),
            sql_rules=self._sql_rules(),
        )
        if fix is None:
            system = CHAT_SYSTEM.substitute(**ctx)
            human = CHAT_USER.substitute(question=question)
        else:
            system = CHAT_FIX_SYSTEM.substitute(**ctx)
            human = CHAT_FIX_USER.substitute(
                question=question,
                failed_output=fix['failed_output'],
                error_msg=fix['error_msg'],
            )
        return ChatPromptTemplate.from_messages([
            ('system', _escape_braces(system)),
            ('human', _escape_braces(human)),
        ]).invoke({})

    # ===== 生成与解析 =====

    def _stream_generate(self, question: str):
        """首次生成：流式。逐帧产出 delta，返回完整输出（经 yield from 取回）。"""
        chunks = []
        usage = None
        with span(self._trace_id, 'llm', '生成SQL(流式)',
                  model=settings.LLM_MODEL, attempt=0) as s:
            prompt = self._build_messages(question)
            s.attrs['prompt_chars'] = sum(len(m.content) for m in prompt.to_messages())
            for chunk in self.llm.stream(prompt):
                if chunk.content:
                    chunks.append(chunk.content)
                    yield {'type': 'delta', 'content': chunk.content}
                if getattr(chunk, 'usage_metadata', None):
                    usage = chunk.usage_metadata
            if usage:
                s.attrs['prompt_tokens'] = usage.get('input_tokens')
                s.attrs['completion_tokens'] = usage.get('output_tokens')
        return ''.join(chunks)

    def _regenerate(self, question: str, failed_output: str, error_msg: str) -> str:
        """修复重试：不流式（重试对用户是黑盒，只有最终结果可见）。"""
        with span(self._trace_id, 'llm', '修复重试',
                  model=settings.LLM_MODEL, reason=error_msg[:120]):
            messages = self._build_messages(question, fix={
                'failed_output': failed_output, 'error_msg': error_msg,
            })
            return clean_sql(self.llm.invoke(messages).content)

    @staticmethod
    def _parse_result(text: str) -> dict:
        """解析 LLM 的 JSON 输出。容忍围栏/前后杂文本：取首个 { 到末个 } 的片段。"""
        text = clean_sql(text)
        start, end = text.find('{'), text.rfind('}')
        if start == -1 or end <= start:
            raise ValueError(f'输出中没有 JSON 对象: {text[:120]}')
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f'JSON 解析失败: {e}；原文: {text[:120]}') from e
        sql = obj.get('sql')
        sql = clean_sql(sql).strip() if isinstance(sql, str) and sql.strip() else None
        chart_type = obj.get('chart_type')
        if chart_type not in CHART_MENU:
            chart_type = 'response_table'
        return {
            'thoughts': str(obj.get('thoughts') or '').strip() or '（未给出分析思路）',
            'sql': sql,
            'chart_type': chart_type,
        }

    # ===== 校验与执行 =====

    def _validate(self, sql: str) -> bool:
        if self.dataset and not self._use_duckdb:
            # JSONB 旧路径：dataset_id 白名单防 LLM 幻觉引用未授权数据集。
            # DuckDB 路径：只读连接只挂载本数据集文件，跨数据集从连接层不可达
            # （与外部源同款隔离论证），无需白名单。
            return validate_select_sql(sql, {str(self.dataset.id).lower()})
        return validate_select_sql(sql)

    def _execute(self, sql: str) -> tuple:
        if self.dataset and self._use_duckdb:
            return execute_duckdb_sql(self.dataset, sql)
        if self.dataset:
            return execute_select_sql(sql, infer_types=True)
        from apps.datasources.services.engine import create_engine_for_source
        from apps.datasources.services.nl2sql_external import execute_external_sql
        engine = create_engine_for_source(self.source)
        try:
            return execute_external_sql(engine, sql)
        finally:
            engine.dispose()

    def _save_assistant(self, round_index, parsed, elapsed_ms,
                        success, error='', columns=None, column_types=None,
                        rows=None, row_count=0):
        extra = {'sql': parsed.get('sql'), 'chart_type': parsed.get('chart_type'),
                 'success': success, 'trace_id': self._trace_id}
        if error:
            extra['error'] = error
        if success and parsed.get('sql'):
            extra.update(columns=columns, column_types=column_types,
                         rows=rows, row_count=row_count)
        return ChatMessage.objects.create(
            conversation=self.conversation, round_index=round_index,
            role='assistant', content=parsed.get('thoughts', ''), extra=extra,
        )

    def _record_history(self, question, sql, success, error, elapsed_ms, rows, columns):
        question_embedding = None
        if success:
            from apps.query.services.embedding import embed_question
            with span(self._trace_id, 'embed', '历史问题向量化'):
                try:
                    question_embedding = embed_question(question)
                except Exception:
                    logger.warning('chat: embedding 生成失败，历史照常落库')
        QueryHistory.objects.create(
            dataset=self.dataset, source=self.source,
            user=self.conversation.user,
            question=question, generated_sql=sql or '',
            execution_engine=(
                'duckdb' if self.dataset and self._use_duckdb
                else 'platform-pg' if self.dataset
                else self.source.db_type),
            is_success=success, error_message=error or '',
            execution_time_ms=elapsed_ms,
            result_count=len(rows) if success and rows else 0,
            result_preview=_sanitize_for_json(rows[:20]) if success and rows else None,
            result_columns=columns if success else None,
            question_embedding=question_embedding,
        )

    def _fail(self, round_index, question, parsed, elapsed_ms, error):
        """失败收尾：assistant 消息 + 历史 + error/done 帧。"""
        assistant = self._save_assistant(
            round_index, parsed, elapsed_ms, success=False, error=error)
        if parsed.get('sql'):
            self._record_history(question, parsed['sql'], False, error,
                                 elapsed_ms, [], None)
        return [
            {'type': 'error', 'message': error},
            {'type': 'done', 'message_id': assistant.id, 'success': False,
             'execution_time_ms': elapsed_ms, 'trace_id': self._trace_id},
        ]

    # ===== 主流程 =====

    def stream(self, question: str):
        """流式主流程，产出帧 dict 序列（SSE 包装在视图层）。

        首次生成流式（delta 帧）；JSON 解析失败/执行失败进入修复重试
        （不流式），重试预算 MAX_RETRIES。所有路径最终以 done 帧收尾。
        """
        start_time = time.time()
        self._trace_id = new_trace_id()
        # chat_file：存量数据集惰性物化（失败回退 JSONB 旧路径，见 _use_duckdb）
        if self.dataset:
            from apps.datasets.services.materialize import ensure_materialized
            self._use_duckdb = ensure_materialized(self.dataset, self._trace_id)

        round_index = (ChatMessage.objects.filter(
            conversation=self.conversation
        ).order_by('-round_index').values_list('round_index', flat=True).first() or 0) + 1
        user_msg = ChatMessage.objects.create(
            conversation=self.conversation, round_index=round_index,
            role='user', content=question,
        )
        self._pending_user_msg_id = user_msg.id
        # 会话标题：首轮问题截断
        if not self.conversation.title:
            self.conversation.title = question[:50]
            self.conversation.save(update_fields=['title', 'updated_at'])

        # 1. 首次生成（流式）+ 解析（解析失败走修复重试）
        output = yield from self._stream_generate(question)
        parsed = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                parsed = self._parse_result(output)
                break
            except ValueError as e:
                if attempt >= self.MAX_RETRIES:
                    elapsed = int((time.time() - start_time) * 1000)
                    parsed = {'thoughts': '抱歉，回答生成失败，请换个问法重试。', 'sql': None}
                    yield from self._fail(round_index, question, parsed, elapsed, str(e))
                    return
                output = self._regenerate(
                    question, output, f'输出不是合法 JSON: {e}')

        # 2. 纯文本回答（sql 为 null）：不执行不查库
        if parsed['sql'] is None:
            elapsed = int((time.time() - start_time) * 1000)
            assistant = self._save_assistant(round_index, parsed, elapsed, success=True)
            yield {'type': 'answer', **parsed}
            yield {'type': 'done', 'message_id': assistant.id, 'success': True,
                   'execution_time_ms': elapsed, 'trace_id': self._trace_id}
            return

        # 3. 只读校验（失败不重试——与现有查询路径行为一致）
        with span(self._trace_id, 'sql_validate', '只读校验') as s:
            valid = self._validate(parsed['sql'])
            s.attrs['passed'] = valid
        if not valid:
            elapsed = int((time.time() - start_time) * 1000)
            yield from self._fail(
                round_index, question, parsed, elapsed,
                '生成的SQL包含不允许的操作，仅支持SELECT查询')
            return
        parsed['sql'] = add_limit_clause(parsed['sql'], 1000)

        # 4. 执行 + 失败修复重试
        sql = parsed['sql']
        rows = column_types = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                with span(self._trace_id, 'sql_execute', '执行SQL', attempt=attempt,
                          engine=('duckdb' if self._use_duckdb
                                  else 'platform-pg' if self.dataset
                                  else self.source.db_type)) as s:
                    rows, column_types = self._execute(sql)
                    s.attrs['rows'] = len(rows)
                break
            except Exception as e:
                logger.warning('chat SQL 执行失败 (尝试 %d/%d): %s',
                               attempt + 1, self.MAX_RETRIES, e)
                if attempt >= self.MAX_RETRIES:
                    elapsed = int((time.time() - start_time) * 1000)
                    yield from self._fail(round_index, question, parsed, elapsed, str(e))
                    return
                try:
                    fixed = self._parse_result(self._regenerate(
                        question, sql, f'SQL 执行失败: {e}'))
                except ValueError:
                    continue
                if fixed['sql'] and self._validate(fixed['sql']):
                    parsed = fixed
                    sql = parsed['sql'] = add_limit_clause(fixed['sql'], 1000)

        # 5. 成功收尾
        elapsed = int((time.time() - start_time) * 1000)
        columns = list(column_types.keys())
        view_rows = _sanitize_for_json(rows[:VIEW_ROWS_CAP])
        assistant = self._save_assistant(
            round_index, parsed, elapsed, success=True,
            columns=columns, column_types=column_types,
            rows=view_rows, row_count=len(rows))
        self._record_history(question, sql, True, '', elapsed, rows, columns)
        self.conversation.save(update_fields=['updated_at'])

        yield {'type': 'answer', **parsed}
        yield {'type': 'view', 'columns': columns, 'column_types': column_types,
               'rows': view_rows, 'row_count': len(rows)}
        yield {'type': 'done', 'message_id': assistant.id, 'success': True,
               'execution_time_ms': elapsed, 'trace_id': self._trace_id}
