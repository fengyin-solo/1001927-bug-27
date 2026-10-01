<template>
  <section class="page" data-module="maintjob">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">派发、改派、撤回均按接管班组鉴权：只有当前接管班组与值班管理员能提交变更，其它班组只能查看。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修任务单</button>
        <button class="btn" type="button" @click="exportRows">导出任务清单</button>
        <button class="btn" type="button" @click="exportLedger">导出汇总台账</button>
      </div>
    </header>

    <div class="identity-bar">
      <span class="identity-label">当前操作身份</span>
      <select v-model="identityIndex" @change="applyIdentity">
        <option v-for="(item, index) in identities" :key="item.label" :value="index">{{ item.label }}</option>
      </select>
      <span class="identity-hint" v-if="session.isAdmin">值班管理员可派发任意待派发任务，也可接管/撤回任意在途任务</span>
      <span class="identity-hint" v-else>班组账号仅能对「{{ session.operatorCrew }}」接管的任务提交变更，其它任务只读</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>任务编号</span>
        <input v-model="keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>任务状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ display(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情/记录</button>
            <span v-if="!allowedActions(row).length" class="muted-text">仅可查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的检修任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修任务记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <section class="ledger-block">
      <div class="ledger-head">
        <h3>检修汇总台账（检定结论随任务确认完成落入）</h3>
        <div class="ledger-filters">
          <input v-model="ledgerKeyword" placeholder="按任务编号检索" @keyup.enter="reloadLedger" />
          <input v-model="ledgerCrew" placeholder="按作业班组检索" @keyup.enter="reloadLedger" />
          <button class="btn" type="button" @click="reloadLedger">查询台账</button>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="`ledger-${String(row.id)}`">
            <td v-for="column in ledgerColumns" :key="column">{{ display(row, column) }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">台账暂无数据</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 动作弹窗：派发/改派/确认完成共用 -->
    <div v-if="dialog.action" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialogTitle }}</h3>
        <p class="modal-tip">任务 {{ dialog.row?.['任务编号'] }} · 当前状态 {{ dialog.row?.['任务状态'] }}</p>
        <template v-if="dialog.action === '派发任务'">
          <label class="form-line"><span>作业班组</span><input v-model="dialog.form['作业班组']" placeholder="如：电气检修班" /></label>
          <label class="form-line"><span>负责人</span><input v-model="dialog.form['负责人']" placeholder="如：李工" /></label>
        </template>
        <template v-else-if="dialog.action === '改派'">
          <label class="form-line"><span>接管班组</span><input v-model="dialog.form['接管班组']" placeholder="接管的作业班组" /></label>
          <label class="form-line"><span>接管负责人</span><input v-model="dialog.form['接管负责人']" placeholder="接管负责人" /></label>
        </template>
        <template v-else-if="dialog.action === '确认完成'">
          <label class="form-line"><span>检定结论</span><textarea v-model="dialog.form['检定结论']" placeholder="如：更换备件后运行正常，一次验收合格" rows="3" /></label>
        </template>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitDialog">
            {{ dialog.submitting ? '提交中…' : '提交变更' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <h3>登记检修任务单</h3>
        <label class="form-line"><span>任务编号</span><input v-model="createForm['任务编号']" placeholder="如：MAIN-0101" /></label>
        <label class="form-line"><span>关联机组</span><input v-model="createForm['关联机组']" placeholder="如：TURB-0018" /></label>
        <label class="form-line"><span>检修类型</span><input v-model="createForm['检修类型']" placeholder="如：定期维护" /></label>
        <label class="form-line"><span>计划开始日</span><input v-model="createForm['计划开始日']" placeholder="YYYY-MM-DD" /></label>
        <label class="form-line"><span>计划工时</span><input v-model="createForm['计划工时']" placeholder="如：8" /></label>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
        </footer>
      </div>
    </div>

    <!-- 详情弹窗：与列表读同一份接口数据，刷新后口径一致 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-wide">
        <h3>任务详情 · {{ detail['任务编号'] }}</h3>
        <table class="data-table detail-table">
          <tbody>
            <tr v-for="column in columns" :key="column">
              <th>{{ column }}</th>
              <td>{{ display(detail, column) }}</td>
            </tr>
            <tr>
              <th>检定结论</th>
              <td>{{ display(detail, '检定结论') }}</td>
            </tr>
          </tbody>
        </table>
        <h4>历史派发/改派/撤回记录</h4>
        <table class="data-table">
          <thead>
            <tr><th>类型</th><th>作业班组</th><th>负责人</th><th>操作人</th><th>操作人班组</th><th>时间</th><th>备注</th></tr>
          </thead>
          <tbody>
            <tr v-for="(record, index) in records(detail)" :key="index">
              <td>{{ record['类型'] }}</td>
              <td>{{ record['作业班组'] || '—' }}</td>
              <td>{{ record['负责人'] || '—' }}</td>
              <td>{{ record['操作人'] }}</td>
              <td>{{ record['操作人班组'] }}</td>
              <td>{{ record['时间'] }}</td>
              <td>{{ record['备注'] || '—' }}</td>
            </tr>
            <tr v-if="!records(detail).length">
              <td colspan="7" class="empty-state">暂无派发记录</td>
            </tr>
          </tbody>
        </table>
        <footer class="modal-foot">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { IDENTITY_PRESETS, useSessionStore } from '@/stores/session'

type Cell = string | number | null | undefined
type Row = Record<string, Cell>
interface DispatchRecord {
  类型: string
  作业班组: string
  负责人: string
  操作人: string
  操作人班组: string
  时间: string
  备注?: string
}
type DialogAction = '' | '派发任务' | '改派' | '撤回' | '开始检修' | '确认完成'

const ENDPOINT = '/api/maintjob'
const columns = ['任务编号', '关联机组', '检修类型', '计划开始日', '计划工时', '作业班组', '负责人', '任务状态']
const ledgerColumns = ['任务编号', '关联机组', '检修类型', '作业班组', '负责人', '任务状态', '检定结论', '台账来源', '更新时间']
const statuses = ['待派发', '已派发', '检修中', '已完成']

const session = useSessionStore()
const identities = IDENTITY_PRESETS
const identityIndex = ref(0)

const rows = ref<Row[]>([])
const ledgerRows = ref<Row[]>([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const ledgerKeyword = ref('')
const ledgerCrew = ref('')
const message = ref('')
const messageOk = ref(false)
const creating = ref(false)
const createForm = reactive<Record<string, string>>({})
const detail = ref<Row | null>(null)

const dialog = reactive<{ action: DialogAction; row: Row | null; form: Record<string, string>; submitting: boolean }>({
  action: '',
  row: null,
  form: {},
  submitting: false,
})

const stats = computed(() => {
  const pending = rows.value.filter((row) => row['任务状态'] === '待派发').length
  const running = rows.value.filter((row) => ['已派发', '检修中'].includes(String(row['任务状态']))).length
  const done = rows.value.filter((row) => row['任务状态'] === '已完成').length
  return [
    { label: '待派发任务', value: pending },
    { label: '在途任务（已派发/检修中）', value: running },
    { label: '已完成任务', value: done },
  ]
})

const dialogTitle = computed(() => {
  switch (dialog.action) {
    case '派发任务':
      return '派发任务'
    case '改派':
      return '改派给接管班组'
    case '确认完成':
      return '确认完成并登记检定结论'
    default:
      return '执行动作'
  }
})

function applyIdentity() {
  const item = identities[identityIndex.value]
  session.setIdentity(item.name, item.crew, item.role)
  flash(`已切换为 ${item.label}`, true)
}

function display(row: Row, column: string): string {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function records(row: Row): DispatchRecord[] {
  const value = row['派发记录']
  return Array.isArray(value) ? (value as DispatchRecord[]) : []
}

/** 行内可执行动作：前端按状态与身份只展示有权限的入口，后端仍会二次鉴权。 */
function allowedActions(row: Row): string[] {
  const status = String(row['任务状态'])
  const actions: string[] = []
  if (status === '待派发') {
    if (session.isAdmin) actions.push('派发任务')
    return actions
  }
  if (status === '已完成') return actions
  const canChange = session.isAdmin || row['作业班组'] === session.operatorCrew
  if (!canChange) return actions
  if (status === '已派发') actions.push('开始检修')
  actions.push('改派', '撤回', '确认完成')
  return actions
}

function flash(text: string, ok = false) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function exportLedger() {
  window.open(`${ENDPOINT}/ledger/export`, '_blank')
}

function openCreate() {
  Object.keys(createForm).forEach((key) => delete createForm[key])
  creating.value = true
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      flash(payload.detail ?? payload.message ?? '登记失败')
      return
    }
    creating.value = false
    flash(payload.message ?? '检修任务单已登记', true)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '登记失败')
  }
}

function openDetail(row: Row) {
  // 重新拉取单条详情，确保与列表同源、刷新后一致
  void request(`${ENDPOINT}/${row.id}`)
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error('详情读取失败'))))
    .then((data: Row) => {
      detail.value = data
    })
    .catch((error: unknown) => flash(error instanceof Error ? error.message : '详情读取失败'))
}

function runAction(action: string, row: Row) {
  if (action === '撤回') {
    const crew = display(row, '作业班组')
    if (!window.confirm(`确认把任务 ${row['任务编号']} 从「${crew}」撤回至待派发？撤回后该班组不再持有任务。`)) {
      return
    }
    void submitAction(action, row, {})
    return
  }
  if (action === '开始检修') {
    void submitAction(action, row, {})
    return
  }
  dialog.action = action as DialogAction
  dialog.row = row
  dialog.form = {}
  dialog.submitting = false
}

function closeDialog() {
  dialog.action = ''
  dialog.row = null
  dialog.form = {}
}

async function submitDialog() {
  if (!dialog.action || !dialog.row) return
  await submitAction(dialog.action, dialog.row, { ...dialog.form })
}

async function submitAction(action: string, row: Row, values: Record<string, string>) {
  dialog.submitting = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...values } }),
    })
    const payload = await response.json()
    closeDialog()
    if (!response.ok || !payload.ok) {
      // 越权/非法流转：后端给的原因直接展示给用户
      flash(payload.detail ?? payload.message ?? '动作未生效')
      return
    }
    flash(payload.message ?? `动作「${action}」已生效`, true)
    await reload()
    await reloadLedger()
  } catch (error) {
    closeDialog()
    flash(error instanceof Error ? error.message : '动作未生效，请稍后重试')
  } finally {
    dialog.submitting = false
  }
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function reload() {
  try {
    const response = await request(`${ENDPOINT}${buildQuery()}`)
    if (!response.ok) throw new Error('检修任务单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    flash(error instanceof Error ? error.message : '检修任务列表读取失败')
  }
}

async function reloadLedger() {
  try {
    const params = new URLSearchParams()
    if (ledgerKeyword.value) params.set('keyword', ledgerKeyword.value)
    if (ledgerCrew.value) params.set('crew', ledgerCrew.value)
    const response = await request(`${ENDPOINT}/ledger?${params.toString()}`)
    if (!response.ok) throw new Error('汇总台账读取失败')
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
  } catch (error) {
    flash(error instanceof Error ? error.message : '汇总台账读取失败')
  }
}

onMounted(() => {
  void reload()
  void reloadLedger()
})
</script>

<style scoped>
.identity-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.identity-label { color: var(--muted); }
.identity-bar select { padding: 4px 8px; }
.identity-hint { color: var(--muted); }
.muted-text { color: var(--muted); font-size: 12px; }
.ok-text { color: #067647; }
.ledger-block { margin-top: 20px; }
.ledger-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.ledger-head h3 { font-size: 15px; margin: 0; }
.ledger-filters { display: flex; gap: 8px; }
.ledger-filters input { padding: 5px 8px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  width: 420px;
  max-height: 85vh;
  overflow: auto;
}
.modal-wide { width: 820px; }
.modal h3 { margin: 0 0 6px; font-size: 16px; }
.modal h4 { margin: 14px 0 6px; font-size: 14px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.form-line { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 13px; }
.form-line span { width: 72px; color: var(--muted); flex: none; }
.form-line input, .form-line textarea { flex: 1; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.detail-table th { width: 130px; color: var(--muted); }
</style>
