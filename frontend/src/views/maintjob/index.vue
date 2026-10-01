<template>
  <section class="page" data-module="maintjob">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">任务派发、改派与撤回按接管班组授权；只有接管班组与值班管理员能提交变更，其它班组仅可查看。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :class="{ primary: tab === 'tasks' }" type="button" @click="tab = 'tasks'">任务单</button>
        <button class="btn" :class="{ primary: tab === 'ledger' }" type="button" @click="switchTab('ledger')">汇总台账</button>
        <button class="btn" type="button" @click="exportRows">导出检修任务清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 任务单列表 -->
    <template v-if="tab === 'tasks'">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>任务编号</span>
          <input v-model="keyword" placeholder="按任务编号检索" />
        </label>
        <label class="filter-item">
          <span>任务状态</span>
          <select v-model="statusFilter">
            <option value="">全部</option>
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
            <td v-for="column in columns" :key="column">
              <button v-if="column === '任务编号'" class="link" type="button" @click="openDetail(row)">
                {{ row[column] }}
              </button>
              <template v-else>{{ row[column] || '—' }}</template>
            </td>
            <td class="row-actions">
              <button
                v-for="action in actionsFor(row)"
                :key="action.name"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action.name }}
              </button>
              <button class="link" type="button" @click="openDetail(row)">详情</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的检修任务</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 汇总台账 -->
    <template v-else>
      <form class="filter-bar" @submit.prevent="loadLedger">
        <label class="filter-item">
          <span>任务编号</span>
          <input v-model="ledgerKeyword" placeholder="按任务编号检索检定结论" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="String(row.id)">
            <td v-for="column in ledgerColumns" :key="column">{{ row[column] || '—' }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">暂无台账记录，任务确认完成后检定结论自动落到这里</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 详情抽屉：派发/改派/撤回历史 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>任务 {{ detail['任务编号'] }} 派发详情</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detail[field] || '—' }}</dd>
          </template>
        </dl>
        <h4 class="detail-sub">派发 / 改派 / 撤回记录</h4>
        <table class="data-table history-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>动作</th>
              <th>接管班组</th>
              <th>负责人</th>
              <th>操作人</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in detail['派发记录']" :key="String(item.id)">
              <td>{{ item['时间'] }}</td>
              <td>{{ item['动作'] }}</td>
              <td>{{ item['作业班组'] || '—' }}</td>
              <td>{{ item['负责人'] || '—' }}</td>
              <td>{{ item['操作人'] }}（{{ item['操作班组'] }}）</td>
              <td>{{ item['备注'] || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <h4 class="detail-sub">汇总台账</h4>
        <p v-if="detail['台账']" class="ledger-line">
          检定结论：<strong>{{ detail['台账']['检定结论'] }}</strong>
          （更新于 {{ detail['台账']['更新时间'] }}）
        </p>
        <p v-else class="muted-line">任务尚未完成，暂无检定结论台账记录</p>
      </aside>
    </div>

    <!-- 派发/改派表单 -->
    <div v-if="form.open" class="drawer-mask" @click.self="form.open = false">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>{{ form.actionName }}：{{ form.row?.['任务编号'] }}</h3>
          <button class="btn ghost" type="button" @click="form.open = false">关闭</button>
        </header>
        <form class="action-form" @submit.prevent="submitForm">
          <label v-if="form.actionName === '派发任务' || form.actionName === '改派任务'">
            <span>接管班组 *</span>
            <input v-model="form.team" list="team-options" placeholder="选择或输入接管作业班组" />
            <datalist id="team-options">
              <option v-for="team in teamOptions" :key="team" :value="team" />
            </datalist>
          </label>
          <label v-if="form.actionName === '派发任务' || form.actionName === '改派任务'">
            <span>负责人</span>
            <input v-model="form.leader" placeholder="不填则按班组默认负责人" />
          </label>
          <label v-if="form.actionName === '确认完成'">
            <span>检定结论</span>
            <textarea v-model="form.conclusion" rows="3" placeholder="如：合格 / 整改后合格；不填则取验收单结论"></textarea>
          </label>
          <label>
            <span>备注</span>
            <input v-model="form.remark" placeholder="可选" />
          </label>
          <p v-if="form.error" class="error-text">{{ form.error }}</p>
          <div class="form-actions">
            <button class="btn primary" type="submit">提交</button>
            <button class="btn ghost" type="button" @click="form.open = false">取消</button>
          </div>
        </form>
      </aside>
    </div>

    <footer class="page-foot">
      <span v-if="tab === 'tasks'">共 {{ total }} 条检修任务记录</span>
      <span v-else>共 {{ ledgerRows.length }} 条台账记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { errorMessage, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
type HistoryRow = Record<string, string | number>

const ENDPOINT = '/api/maintjob'
const session = useSessionStore()

const columns = ['任务编号', '关联机组', '检修类型', '计划开始日', '计划工时', '作业班组', '负责人', '任务状态']
const statuses = ['待派发', '已派发', '检修中', '已完成']
const ledgerColumns = ['任务编号', '关联机组', '检修类型', '作业班组', '检定结论', '完成日期', '登记人', '更新时间']
const detailFields = ['任务编号', '关联机组', '检修类型', '计划开始日', '计划工时', '作业班组', '负责人', '任务状态']
const teamOptions = ['机械一班', '机械二班', '电气二班']

interface ActionDef {
  name: string
  needsForm: boolean
}

const ALL_ACTIONS: ActionDef[] = [
  { name: '派发任务', needsForm: true },
  { name: '改派任务', needsForm: true },
  { name: '撤回任务', needsForm: false },
  { name: '开始检修', needsForm: false },
  { name: '确认完成', needsForm: true },
]

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(false)
const keyword = ref('')
const statusFilter = ref('')

const tab = ref<'tasks' | 'ledger'>('tasks')
const ledgerRows = ref<Row[]>([])
const ledgerKeyword = ref('')

const detail = ref<(Row & { 派发记录?: HistoryRow[]; 台账?: Row }) | null>(null)

const form = reactive({
  open: false,
  actionName: '',
  row: null as Row | null,
  team: '',
  leader: '',
  conclusion: '',
  remark: '',
  error: '',
})

const stats = computed(() => [
  { label: '待派发任务', value: rows.value.filter((r) => r['任务状态'] === '待派发').length },
  { label: '检修中任务', value: rows.value.filter((r) => r['任务状态'] === '检修中').length },
  // 依赖 session.team：顶栏切换账号后卡片自动重算
  { label: `「${session.team}」接管`, value: rows.value.filter((r) => r['作业班组'] === session.team).length },
])

/** 按任务状态给出可见动作；是否点得动由后端按接管班组最终裁决。 */
function actionsFor(row: Row): ActionDef[] {
  switch (row['任务状态']) {
    case '待派发':
      return [ALL_ACTIONS[0]]
    case '已派发':
      return [ALL_ACTIONS[1], ALL_ACTIONS[2], ALL_ACTIONS[3]]
    case '检修中':
      return [ALL_ACTIONS[1], ALL_ACTIONS[2], ALL_ACTIONS[4]]
    default:
      return []
  }
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

async function switchTab(next: 'tasks' | 'ledger') {
  tab.value = next
  if (next === 'ledger') {
    await loadLedger()
  } else {
    await reload()
  }
}

async function reload() {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('检修任务单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 详情抽屉开着时同步刷新，保证列表/详情一致
    if (detail.value) {
      const latest = rows.value.find((r) => r.id === detail.value?.id)
      if (latest) {
        await openDetail(latest)
      }
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '检修任务列表读取失败')
  }
}

async function loadLedger() {
  const params = new URLSearchParams()
  if (ledgerKeyword.value) params.set('keyword', ledgerKeyword.value)
  try {
    const response = await request(`${ENDPOINT}/ledger?${params.toString()}`)
    if (!response.ok) {
      throw new Error('汇总台账读取失败')
    }
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
  } catch (error) {
    flash(error instanceof Error ? error.message : '汇总台账读取失败')
  }
}

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('任务详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    flash(error instanceof Error ? error.message : '任务详情读取失败')
  }
}

function runAction(action: ActionDef, row: Row) {
  Object.assign(form, {
    actionName: action.name,
    row,
    team: action.name === '派发任务' ? session.team : String(row['作业班组'] ?? ''),
    leader: action.name === '派发任务' ? (session.isAdmin ? '' : session.operator) : String(row['负责人'] ?? ''),
    conclusion: '',
    remark: '',
    error: '',
  })
  // 开始检修/撤回不需要参数：撤回先二次确认，再直接提交；其余动作走抽屉表单
  if (!action.needsForm) {
    if (action.name === '撤回任务' && !window.confirm('确认撤回该任务？撤回后任务退回待派发，原班组不再持有。')) {
      return
    }
    void submitForm()
    return
  }
  form.open = true
}

function buildValues(): Record<string, string> {
  const values: Record<string, string> = { action: form.actionName }
  if (form.actionName === '派发任务' || form.actionName === '改派任务') {
    values['作业班组'] = form.team.trim()
    values['负责人'] = form.leader.trim()
  }
  if (form.actionName === '确认完成') {
    values['检定结论'] = form.conclusion.trim()
  }
  if (form.remark.trim()) {
    values.remark = form.remark.trim()
  }
  return values
}

async function submitForm() {
  if (!form.row) {
    return
  }
  if ((form.actionName === '派发任务' || form.actionName === '改派任务') && !form.team.trim()) {
    form.error = '接管班组必填'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${form.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: buildValues() }),
    })
    if (!response.ok) {
      form.error = await errorMessage(response, '检修任务动作未生效，请稍后重试')
      return
    }
    const payload = (await response.json()) as { message?: string }
    form.open = false
    flash(payload.message ?? '操作已生效', true)
    await reload()
    if (tab.value === 'ledger') {
      await loadLedger()
    }
  } catch (error) {
    form.error = error instanceof Error ? error.message : '检修任务操作失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.ok-text { color: #067647; }
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 20;
}
.drawer {
  width: 720px;
  max-width: 92vw;
  background: #fff;
  height: 100%;
  overflow-y: auto;
  padding: 16px 20px;
}
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.drawer-head h3 { margin: 0; font-size: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: 90px 1fr 90px 1fr;
  gap: 6px 10px;
  font-size: 13px;
  margin: 12px 0;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.detail-sub { font-size: 14px; margin: 16px 0 8px; }
.history-table th, .history-table td { font-size: 12px; padding: 6px 8px; }
.muted-line { color: var(--muted); font-size: 13px; }
.ledger-line { font-size: 13px; }
.action-form { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.action-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.action-form input, .action-form textarea { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.form-actions { display: flex; gap: 8px; }
</style>
