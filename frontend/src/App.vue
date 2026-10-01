<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">风电场机组运维平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向风电场站台账、机组部件监测、变桨偏航调试、缺陷处置与上网电量结算的一体化运维后台。</span>
        <span class="head-user">
          当前值班：{{ store.operator }}（{{ store.team }} · {{ store.role }}） · {{ store.shiftLabel }}
          <label class="identity-switch">
            切换账号
            <select :value="store.operator" @change="switchIdentity">
              <option v-for="item in identities" :key="item.name" :value="item.name">
                {{ item.name }}｜{{ item.team }}｜{{ item.role }}
              </option>
            </select>
          </label>
        </span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { IDENTITIES, useSessionStore } from '@/stores/session'

const store = useSessionStore()
const identities = IDENTITIES

function switchIdentity(event: Event) {
  const name = (event.target as HTMLSelectElement).value
  const identity = identities.find((item) => item.name === name)
  if (identity) {
    store.setIdentity(identity)
  }
}

const navItems = [{ label: "运营概览", path: "/" }, { label: "风电场站", path: "/windfarm" }, { label: "风电机组", path: "/turbine" }, { label: "叶片", path: "/blade" }, { label: "齿轮箱", path: "/gearbox" }, { label: "发电机", path: "/generator" }, { label: "变桨系统", path: "/pitch" }, { label: "偏航系统", path: "/yaw" }, { label: "测风塔", path: "/metmast" }, { label: "集电线路", path: "/collector" }, { label: "升压站", path: "/substation" }, { label: "功率预测", path: "/forecast" }, { label: "振动监测", path: "/vibration" }, { label: "缺陷登记", path: "/defect" }, { label: "检修任务", path: "/maintjob" }, { label: "备件领用", path: "/spare" }, { label: "巡视检查", path: "/patrol" }, { label: "验收确认", path: "/accept" }, { label: "电量结算", path: "/settle" }]
</script>

<style scoped>
.identity-switch { margin-left: 10px; font-size: 12px; }
.identity-switch select { margin-left: 4px; font-size: 12px; padding: 2px 4px; }
</style>
