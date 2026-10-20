<template>
  <div class="page-container">
    <div class="page-header">
      <h2>外部数据源</h2>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="openCreateDialog">
          连接数据库
        </el-button>
      </div>
    </div>

    <div class="page-section">
      <el-table :data="sources" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="DB_TAGS[row.db_type]?.type || 'info'">
              {{ DB_TAGS[row.db_type]?.label || row.db_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.db_type === 'sqlite' ? row.database : `${row.host}:${row.port}/${row.database}` }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'danger'">
              {{ row.status === 'active' ? '可用' : '连接失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近测试" min-width="150">
          <template #default="{ row }">{{ formatTime(row.last_tested_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-tooltip content="查询" placement="top">
                <el-button class="action-icon-btn" link type="primary" :icon="Search"
                           @click="goQuery(row)" />
              </el-tooltip>
              <el-tooltip content="测试连通" placement="top">
                <el-button class="action-icon-btn" link type="success" :icon="Connection"
                           @click="handleTest(row)" />
              </el-tooltip>
              <el-tooltip content="删除" placement="top">
                <el-button class="action-icon-btn" link type="danger" :icon="Delete"
                           @click="handleDelete(row)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && sources.length === 0" description="还没有数据源，连接一个数据库开始查询" />
    </div>

    <!-- 新建数据源对话框（先测试连通，成功才保存） -->
    <el-dialog v-model="createVisible" title="连接数据库" width="520px">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如：生产销售库" maxlength="255" />
        </el-form-item>
        <el-form-item label="类型" prop="db_type">
          <el-radio-group v-model="form.db_type" @change="onTypeChange">
            <el-radio value="mysql">MySQL</el-radio>
            <el-radio value="postgresql">PostgreSQL</el-radio>
            <el-radio value="sqlite">SQLite</el-radio>
            <el-radio value="clickhouse">ClickHouse</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="form.db_type !== 'sqlite'">
          <el-form-item label="主机" prop="host">
            <el-input v-model="form.host" placeholder="如 127.0.0.1" />
          </el-form-item>
          <el-form-item label="端口" prop="port">
            <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
          </el-form-item>
        </template>
        <el-form-item :label="form.db_type === 'sqlite' ? '库文件' : '数据库'" prop="database">
          <el-input v-model="form.database"
                    :placeholder="form.db_type === 'sqlite' ? '服务器上的 .db 文件绝对路径' : '库名'" />
        </el-form-item>
        <template v-if="form.db_type !== 'sqlite'">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" autocomplete="off" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
          </el-form-item>
        </template>
        <el-form-item label="业务说明">
          <el-input v-model="form.business_description" type="textarea" :rows="2"
                    placeholder="库/表的业务背景（可选），帮助 AI 理解字段含义" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="testForm" :loading="testing">
          测试连接
        </el-button>
        <el-button type="primary" @click="saveForm" :loading="saving">
          保存
        </el-button>
      </template>
      <el-alert v-if="testResult" :closable="false"
                :title="testResult.ok ? `连接成功：${testResult.server_version}` : testResult.error"
                :type="testResult.ok ? 'success' : 'error'" show-icon class="test-result" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, Connection, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { datasourceApi, type DataSource } from '../api/datasource'

const router = useRouter()
const loading = ref(false)
const sources = ref<DataSource[]>([])

const DEFAULT_PORTS: Record<string, number> = {
  mysql: 3306, postgresql: 5432, clickhouse: 9000,
}
const DB_TAGS: Record<string, { label: string; type: string }> = {
  mysql: { label: 'MySQL', type: 'warning' },
  postgresql: { label: 'PostgreSQL', type: 'success' },
  sqlite: { label: 'SQLite', type: 'info' },
  clickhouse: { label: 'ClickHouse', type: 'danger' },
}

const createVisible = ref(false)
const formRef = ref<FormInstance>()
const form = ref({
  name: '', db_type: 'mysql', host: '', port: 3306,
  database: '', username: '', password: '', business_description: '',
})
const testing = ref(false)
const saving = ref(false)
const testResult = ref<{ ok: boolean; server_version?: string; error?: string } | null>(null)

// 必填校验：字段为空时红字提示（不再只靠按钮置灰，用户能知道缺什么）
const requiredRule = (label: string) => [{
  required: true, message: `请填写${label}`, trigger: 'blur' },
]
// SQLite（本地文件库）无主机/凭据，连接字段只校验库文件路径
const isSqlite = () => form.value.db_type === 'sqlite'
const formRules: FormRules = {
  name: requiredRule('数据源名称'),
  db_type: requiredRule('数据库类型'),
  host: [{ required: true, message: '请填写主机地址', trigger: 'blur' }],
  database: [{ required: true, message: '请填写数据库名/库文件路径', trigger: 'blur' }],
  username: [{ required: true, message: '请填写用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请填写密码', trigger: 'blur' }],
}

function openCreateDialog() {
  form.value = {
    name: '', db_type: 'mysql', host: '', port: 3306,
    database: '', username: '', password: '', business_description: '',
  }
  testResult.value = null
  formRef.value?.clearValidate()
  createVisible.value = true
}

function onTypeChange() {
  form.value.port = DEFAULT_PORTS[form.value.db_type] || 0
}

/** 测试连接只校验连接相关字段（名称可以后填） */
async function validateConnectionFields(): Promise<boolean> {
  if (!formRef.value) return false
  try {
    const fields = isSqlite()
      ? ['db_type', 'database']
      : ['db_type', 'host', 'port', 'database', 'username', 'password']
    await formRef.value.validateField(fields)
    return true
  } catch {
    return false
  }
}

async function testForm() {
  if (!(await validateConnectionFields())) return
  testing.value = true
  testResult.value = null
  try {
    const res = await datasourceApi.testParams({ ...form.value })
    testResult.value = { ok: true, server_version: res.data.server_version }
  } catch (e: any) {
    testResult.value = { ok: false, error: e?.response?.data?.error || e?.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function saveForm() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    await datasourceApi.create({ ...form.value, name: form.value.name.trim() })
    ElMessage.success('数据源已保存')
    createVisible.value = false
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleTest(row: DataSource) {
  try {
    const res = await datasourceApi.test(row.id)
    ElMessage.success(`连接成功：${res.data.server_version}`)
    row.status = 'active'
    row.last_tested_at = new Date().toISOString()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '连接失败')
    row.status = 'error'
  }
}

async function handleDelete(row: DataSource) {
  try {
    await ElMessageBox.confirm(
      `确定删除数据源"${row.name}"吗？其历史查询记录将保留但无法重跑。`,
      '删除数据源', { type: 'warning' },
    )
  } catch { return }
  try {
    await datasourceApi.remove(row.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

function goQuery(row: DataSource) {
  // 查询交互已统一到 AI 对话页（chat_db 场景）
  router.push({ path: '/chat', query: { source: row.id } })
}

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

async function fetchList() {
  loading.value = true
  try {
    const res = await datasourceApi.getList()
    sources.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '获取数据源列表失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchList)
</script>

<style scoped>
.test-result {
  margin-top: 12px;
}
</style>
