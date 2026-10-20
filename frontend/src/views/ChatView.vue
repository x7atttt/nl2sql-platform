<template>
  <div class="chat-page">
    <!-- 会话侧边栏 -->
    <aside class="chat-aside">
      <div class="aside-header">
        <span class="aside-title">会话</span>
        <el-button type="primary" size="small" :icon="Plus" @click="openCreateDialog">
          新对话
        </el-button>
      </div>
      <div class="conv-list">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === activeId }"
          @click="selectConversation(c.id)"
        >
          <div class="conv-main">
            <div class="conv-title">{{ c.title || '新对话' }}</div>
            <div class="conv-meta">
              <el-tag size="small" :type="c.chat_mode === 'chat_file' ? 'success' : 'warning'">
                {{ c.chat_mode === 'chat_file' ? c.dataset_name : c.source_name }}
              </el-tag>
            </div>
          </div>
          <el-icon class="conv-delete" title="删除会话" @click.stop="removeConversation(c.id)">
            <Delete />
          </el-icon>
        </div>
        <el-empty v-if="!conversations.length" description="还没有对话" :image-size="70" />
      </div>
    </aside>

    <!-- 对话主区 -->
    <section class="chat-main">
      <template v-if="activeConv">
        <header class="chat-header">
          <div class="chat-header-title">{{ activeConv.title || '新对话' }}</div>
          <div class="chat-header-meta">
            <el-tag v-if="activeConv.skill" size="small" type="danger" effect="dark">
              技能 · {{ activeConv.skill }}
            </el-tag>
            <el-tag size="small" effect="plain">
              {{ activeConv.chat_mode === 'chat_file'
                ? `文件数据集 · ${activeConv.dataset_name}`
                : `外部数据源 · ${activeConv.source_name}（${activeConv.source_db_type}）` }}
            </el-tag>
          </div>
        </header>

        <div ref="scrollRef" class="message-area">
          <!-- 空会话：推荐问题引导 -->
          <div v-if="!messages.length" class="empty-hint">
            <div class="empty-hint-title">向数据提问吧</div>
            <div v-if="suggestedQuestions.length" class="suggest-chips">
              <span
                v-for="q in suggestedQuestions"
                :key="q"
                class="suggest-chip"
                @click="input = q"
              >{{ q }}</span>
            </div>
          </div>

          <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.role">
            <div class="bubble" :class="msg.role">
              <!-- 用户：问题原文 -->
              <template v-if="msg.role === 'user'">{{ msg.content }}</template>

              <!-- 助手 -->
              <template v-else>
                <!-- 流式进行中：缓冲文本 + 光标 -->
                <div v-if="msg.streaming" class="stream-buffer">
                  {{ msg.buffer || '正在思考…' }}<span class="cursor" />
                </div>
                <template v-else>
                  <div class="thoughts">{{ msg.content }}</div>
                  <el-alert
                    v-if="msg.extra?.error && msg.extra?.success === false"
                    :title="msg.extra.error"
                    type="error"
                    :closable="false"
                    show-icon
                  />
                  <!-- 结果卡片：图表 / 数据 / SQL / 过程 -->
                  <el-tabs
                    v-if="msg.extra?.rows?.length"
                    class="result-tabs"
                    @tab-change="(name: string | number) => name === 'trace' && loadTrace(msg.id as number)"
                  >
                    <el-tab-pane label="图表">
                      <ResultChart
                        v-if="chartKindOf(msg.extra.chart_type)"
                        :data="msg.extra.rows"
                        :columns="msg.extra.columns || []"
                        :column-types="msg.extra.column_types || {}"
                        :preset-type="chartKindOf(msg.extra.chart_type) || undefined"
                      />
                      <div v-else class="no-chart-hint">该结果适合直接看数据，已为你展示表格。</div>
                    </el-tab-pane>
                    <el-tab-pane :label="`数据（${msg.extra.row_count}）`">
                      <el-table :data="(msg.extra.rows || []).slice(0, 100)" size="small" max-height="320">
                        <el-table-column
                          v-for="col in msg.extra.columns"
                          :key="col"
                          :prop="col"
                          :label="col"
                          min-width="120"
                          show-overflow-tooltip
                        />
                      </el-table>
                      <div v-if="(msg.extra.row_count || 0) > 100" class="more-rows-hint">
                        仅展示前 100 行，共 {{ msg.extra.row_count }} 行
                      </div>
                    </el-tab-pane>
                    <el-tab-pane label="SQL">
                      <div class="sql-block-wrap">
                        <pre class="sql-block">{{ msg.extra.sql }}</pre>
                        <el-button size="small" text :icon="CopyDocument" @click="copySql(msg.extra.sql || '')">
                          复制
                        </el-button>
                      </div>
                    </el-tab-pane>
                    <el-tab-pane v-if="typeof msg.id === 'number'" name="trace">
                      <template #label>过程</template>
                      <el-timeline v-if="traceOf(msg.id)?.length" class="trace-timeline">
                        <el-timeline-item
                          v-for="(s, i) in traceOf(msg.id)"
                          :key="i"
                          :type="s.status === 'error' ? 'danger' : 'success'"
                          :timestamp="`${s.duration_ms}ms`"
                        >
                          <span class="trace-name">{{ s.name }}</span>
                          <el-tag size="small" :type="s.status === 'error' ? 'danger' : 'success'">
                            {{ s.status === 'error' ? '失败' : '成功' }}
                          </el-tag>
                          <div v-if="s.attributes" class="trace-attrs">
                            <span v-for="(v, k) in s.attributes" :key="k">{{ k }}: {{ v }}</span>
                          </div>
                        </el-timeline-item>
                      </el-timeline>
                      <div v-else class="no-chart-hint">{{ traceLoading ? '加载中…' : '暂无过程数据' }}</div>
                    </el-tab-pane>
                  </el-tabs>
                </template>
              </template>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <footer class="input-area">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="向数据提问，如：各区域销售额对比（Enter 发送，Shift+Enter 换行）"
            :disabled="streaming"
            @keydown.enter.exact.prevent="send"
          />
          <el-button
            type="primary"
            class="send-btn"
            :loading="streaming"
            :disabled="!input.trim()"
            @click="send"
          >发送</el-button>
        </footer>
      </template>

      <!-- 未选会话 -->
      <div v-else class="no-conv">
        <el-icon :size="42" color="#a0cfff"><ChatDotRound /></el-icon>
        <div class="no-conv-title">AI 数据对话</div>
        <div class="no-conv-desc">连接数据源或选择数据集，用自然语言完成查询与分析</div>
        <el-button type="primary" round @click="openCreateDialog">开始对话</el-button>
      </div>
    </section>

    <!-- 新建会话 -->
    <el-dialog v-model="dialogVisible" title="新建对话" width="440px">
      <el-form label-width="80px">
        <el-form-item label="对话对象">
          <el-radio-group v-model="dialogMode">
            <el-radio-button value="chat_file">文件数据集</el-radio-button>
            <el-radio-button value="chat_db">外部数据源</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="技能" v-if="skillOptions.length">
          <el-select v-model="dialogSkill" placeholder="不使用技能" clearable style="width: 100%">
            <el-option
              v-for="sk in skillOptions"
              :key="sk.name"
              :label="sk.name"
              :value="sk.name"
            >
              <span style="float: left">{{ sk.name }}</span>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                {{ sk.description.slice(0, 16) }}…
              </span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item :label="dialogMode === 'chat_file' ? '数据集' : '数据源'">
          <el-select
            v-model="dialogResource"
            placeholder="请选择"
            style="width: 100%"
            :loading="dialogLoading"
          >
            <template v-if="dialogMode === 'chat_file'">
              <el-option
                v-for="d in datasetOptions"
                :key="d.id"
                :label="d.name"
                :value="d.id"
                :disabled="d.status !== 'completed'"
              />
            </template>
            <template v-else>
              <el-option
                v-for="s in sourceOptions"
                :key="s.id"
                :label="`${s.name}（${s.db_type}）`"
                :value="s.id"
              />
            </template>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!dialogResource" @click="createConversation">
          创建并开始
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, CopyDocument, Delete, Plus } from '@element-plus/icons-vue'
import ResultChart from '../components/ResultChart.vue'
import { chatApi, type ChatMessageItem, type ConversationItem, type TraceSpanItem } from '../api/chat'
import { datasetApi } from '../api/dataset'
import { datasourceApi } from '../api/datasource'

const route = useRoute()

/** 帧图表类型 → ResultChart 图表类型（response_table 等不适配图表的返回 null） */
const CHART_KIND: Record<string, 'bar' | 'line' | 'area' | 'pie' | 'scatter' | null> = {
  response_bar_chart: 'bar',
  response_line_chart: 'line',
  response_area_chart: 'area',
  response_pie_chart: 'pie',
  response_scatter_chart: 'scatter',
  response_table: null,
}

interface RenderMessage {
  id: number | string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  buffer?: string
  extra?: ChatMessageItem['extra']
}

const conversations = ref<ConversationItem[]>([])
const activeId = ref('')
const activeConv = computed(() => conversations.value.find((c) => c.id === activeId.value))
const messages = ref<RenderMessage[]>([])
const suggestedQuestions = ref<string[]>([])

const input = ref('')
const streaming = ref(false)
const scrollRef = ref<HTMLElement>()

// 新建会话对话框
const dialogVisible = ref(false)
const dialogMode = ref<'chat_file' | 'chat_db'>('chat_file')
const dialogResource = ref('')
const dialogLoading = ref(false)
const dialogSkill = ref('')
const skillOptions = ref<{ name: string; description: string }[]>([])
const datasetOptions = ref<{ id: string; name: string; status: string }[]>([])
const sourceOptions = ref<{ id: string; name: string; db_type: string }[]>([])

function chartKindOf(t?: string | null) {
  return t ? CHART_KIND[t] ?? null : null
}

// 回答过程追溯（"过程"Tab 懒加载）
const traceCache = ref<Record<number, TraceSpanItem[]>>({})
const traceLoading = ref(false)

function traceOf(id: number) {
  return traceCache.value[id]
}

async function loadTrace(id: number) {
  if (!id || traceCache.value[id]) return
  traceLoading.value = true
  try {
    const res = await chatApi.getTrace(id)
    traceCache.value[id] = res.data.spans
  } catch {
    traceCache.value[id] = []
  } finally {
    traceLoading.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  })
}

async function loadConversations() {
  const res = await chatApi.listConversations()
  conversations.value = res.data.results
}

async function selectConversation(id: string) {
  if (streaming.value) return
  activeId.value = id
  const res = await chatApi.getConversation(id)
  messages.value = res.data.messages.map((m) => ({
    id: m.id, role: m.role, content: m.content, extra: m.extra,
  }))
  // 空会话展示数据集推荐问题（chat_file 时）
  suggestedQuestions.value = []
  const conv = res.data.conversation
  if (!messages.value.length && conv.chat_mode === 'chat_file' && conv.dataset_id) {
    try {
      const detail = await datasetApi.getDetail(conv.dataset_id)
      suggestedQuestions.value = detail.data.suggested_questions || []
    } catch { /* 推荐是锦上添花，失败静默 */ }
  }
  scrollToBottom()
}

async function removeConversation(id: string) {
  await ElMessageBox.confirm('删除该会话及全部消息？', '删除会话', { type: 'warning' })
  await chatApi.removeConversation(id)
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (activeId.value === id) {
    activeId.value = ''
    messages.value = []
  }
  ElMessage.success('已删除')
}

function openCreateDialog() {
  dialogVisible.value = true
  dialogResource.value = ''
  void loadDialogOptions()
}

async function loadDialogOptions() {
  dialogLoading.value = true
  if (!skillOptions.value.length) {
    try {
      const res = await chatApi.listSkills()
      skillOptions.value = res.data.results
    } catch { /* 技能列表失败不阻塞建会话 */ }
  }
  try {
    if (dialogMode.value === 'chat_file') {
      const res = await datasetApi.getList({ page: 1 })
      datasetOptions.value = res.data.results
    } else {
      const res = await datasourceApi.getList()
      sourceOptions.value = res.data
    }
  } finally {
    dialogLoading.value = false
  }
}

async function createConversation() {
  const payload = dialogMode.value === 'chat_file'
    ? { chat_mode: 'chat_file', dataset_id: dialogResource.value,
        skill: dialogSkill.value || undefined }
    : { chat_mode: 'chat_db', source_id: dialogResource.value,
        skill: dialogSkill.value || undefined }
  const res = await chatApi.createConversation(payload)
  dialogVisible.value = false
  await loadConversations()
  await selectConversation(res.data.id)
}

async function send() {
  const question = input.value.trim()
  if (!question || streaming.value || !activeConv.value) return
  input.value = ''
  streaming.value = true

  // 乐观插入：用户消息 + 流式中的助手占位
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: question })
  const pending: RenderMessage = {
    id: `a-${Date.now()}`, role: 'assistant', content: '',
    streaming: true, buffer: '', extra: null,
  }
  messages.value.push(pending)
  scrollToBottom()

  try {
    await chatApi.streamChat(activeId.value, question, {
      onDelta: (text) => {
        pending.buffer = (pending.buffer || '') + text
        scrollToBottom()
      },
      onAnswer: (frame) => {
        pending.content = frame.thoughts || ''
        pending.extra = { sql: frame.sql ?? null, chart_type: frame.chart_type ?? null }
      },
      onView: (frame) => {
        pending.extra = {
          sql: pending.extra?.sql ?? null,
          chart_type: pending.extra?.chart_type ?? null,
          columns: frame.columns,
          column_types: frame.column_types,
          rows: frame.rows,
          row_count: frame.row_count,
        }
      },
      onError: (message) => {
        pending.extra = { ...(pending.extra || {}), success: false, error: message }
      },
      onDone: (frame) => {
        // 换成真实消息 id：过程 Tab 的 trace 拉取要用它
        if (frame.message_id) pending.id = frame.message_id
        pending.streaming = false
        streaming.value = false
        scrollToBottom()
        // 首轮问题会成为会话标题，静默刷新列表
        void loadConversations()
      },
    })
  } catch (e: unknown) {
    pending.streaming = false
    pending.extra = {
      ...(pending.extra || {}),
      success: false,
      error: e instanceof Error ? e.message : '连接中断',
    }
  } finally {
    pending.streaming = false
    streaming.value = false
  }
}

function copySql(sql: string) {
  navigator.clipboard.writeText(sql).then(() => ElMessage.success('已复制'))
}

/** 从数据集/数据源页跳转入口：预选资源直接建会话，q 预填问题 */
async function enterFromQuery(datasetId?: string, sourceId?: string) {
  try {
    const payload = datasetId
      ? { chat_mode: 'chat_file', dataset_id: datasetId }
      : { chat_mode: 'chat_db', source_id: sourceId as string }
    const res = await chatApi.createConversation(payload)
    await loadConversations()
    await selectConversation(res.data.id)
  } catch { /* request 拦截器已提示错误 */ }
}

onMounted(async () => {
  await loadConversations()
  const { dataset, source, q } = route.query
  if (dataset || source) {
    await enterFromQuery(dataset as string | undefined, source as string | undefined)
    if (q) input.value = String(q)
  }
})
</script>

<style scoped>
.chat-page {
  display: flex;
  height: 100%;
  gap: 12px;
}

/* ===== 会话侧边栏 ===== */
.chat-aside {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
}

.aside-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.aside-title {
  font-weight: 600;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.conv-item:hover {
  background: var(--el-fill-color-light);
}

.conv-item.active {
  background: var(--el-color-primary-light-9);
}

.conv-main {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-meta {
  margin-top: 4px;
}

.conv-delete {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
  visibility: hidden;
}

.conv-item:hover .conv-delete {
  visibility: visible;
}

.conv-delete:hover {
  color: var(--el-color-danger);
}

/* ===== 对话主区 ===== */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
}

.chat-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.chat-header-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.empty-hint {
  text-align: center;
  padding: 48px 0 24px;
}

.empty-hint-title {
  font-size: 15px;
  color: var(--el-text-color-secondary);
  margin-bottom: 16px;
}

.suggest-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.suggest-chip {
  padding: 6px 14px;
  border-radius: 16px;
  border: 1px solid var(--el-border-color);
  font-size: 13px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.15s;
}

.suggest-chip:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

/* ===== 消息气泡 ===== */
.msg-row {
  display: flex;
  margin-bottom: 14px;
}

.msg-row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.65;
}

.bubble.user {
  background: var(--el-color-primary);
  color: #fff;
  border-top-right-radius: 2px;
  white-space: pre-wrap;
}

.bubble.assistant {
  background: var(--el-fill-color-lighter);
  border-top-left-radius: 2px;
  min-width: 200px;
}

.thoughts {
  white-space: pre-wrap;
}

/* 流式缓冲 + 光标 */
.stream-buffer {
  font-family: monospace;
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  min-height: 20px;
}

.cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  background: var(--el-color-primary);
  margin-left: 2px;
  vertical-align: -2px;
  animation: blink 0.9s infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

/* 结果卡片 */
.result-tabs {
  margin-top: 10px;
}

.no-chart-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 8px 0;
}

.more-rows-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sql-block-wrap {
  position: relative;
}

.sql-block-wrap :deep(.el-button) {
  position: absolute;
  top: 6px;
  right: 6px;
}

.sql-block {
  background: #1e1e2e;
  color: #cdd6f4;
  border-radius: 6px;
  padding: 12px;
  padding-right: 60px;
  font-size: 12.5px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

/* 过程追溯时间线 */
.trace-timeline {
  padding: 4px 4px 0;
}

.trace-name {
  font-size: 13px;
  margin-right: 8px;
}

.trace-attrs {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}

/* ===== 输入区 ===== */
.input-area {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.send-btn {
  height: 54px;
}

/* ===== 未选会话 ===== */
.no-conv {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.no-conv-title {
  font-size: 20px;
  font-weight: 600;
}

.no-conv-desc {
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
</style>
