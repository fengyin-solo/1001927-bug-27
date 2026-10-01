import { defineStore } from 'pinia'

export interface Identity {
  name: string
  team: string
  role: string
}

/** 可切换的演示账号：一个值班管理员 + 三个作业班组。 */
export const IDENTITIES: Identity[] = [
  { name: '赵值班', team: '值班室', role: '值班管理员' },
  { name: '张工', team: '机械一班', role: '班组人员' },
  { name: '李工', team: '电气二班', role: '班组人员' },
  { name: '王工', team: '机械二班', role: '班组人员' },
]

const STORAGE_KEY = 'maint-session'

function loadIdentity(): Identity {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Identity>
      if (parsed.name && parsed.team && parsed.role) {
        return parsed as Identity
      }
    }
  } catch {
    // 本地存储不可用时退回默认账号
  }
  return IDENTITIES[0]
}

export const useSessionStore = defineStore('session', {
  state: () => {
    const identity = loadIdentity()
    return {
      operator: identity.name,
      team: identity.team,
      role: identity.role,
      shiftLabel: '白班 08:00-20:00',
      scope: '风电场机组运维平台',
    }
  },
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isAdmin: (state) => state.role === '值班管理员',
    identity: (state): Identity => ({ name: state.operator, team: state.team, role: state.role }),
  },
  actions: {
    setIdentity(identity: Identity) {
      this.operator = identity.name
      this.team = identity.team
      this.role = identity.role
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(identity))
      } catch {
        // 持久化失败不影响当次会话
      }
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
