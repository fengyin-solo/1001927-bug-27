import { defineStore } from 'pinia'

export type OperatorRole = '值班管理员' | '班组账号'

/** 预置几个常用身份，方便在检修任务页切换验证改派/撤回权限口径。 */
export const IDENTITY_PRESETS = [
  { label: '值班管理员 · 赵值班', name: '赵值班', crew: '值班管理组', role: '值班管理员' as OperatorRole },
  { label: '齿轮箱检修班 · 张工', name: '张工', crew: '齿轮箱检修班', role: '班组账号' as OperatorRole },
  { label: '电气检修班 · 李工', name: '李工', crew: '电气检修班', role: '班组账号' as OperatorRole },
  { label: '叶片检修班 · 王工', name: '王工', crew: '叶片检修班', role: '班组账号' as OperatorRole },
  { label: '液压检修班 · 赵工', name: '赵工', crew: '液压检修班', role: '班组账号' as OperatorRole },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '赵值班',
    operatorCrew: '值班管理组',
    operatorRole: '值班管理员' as OperatorRole,
    shiftLabel: '白班 08:00-20:00',
    scope: '风电场机组运维平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isAdmin: (state) => state.operatorRole === '值班管理员',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setIdentity(name: string, crew: string, role: OperatorRole) {
      this.operator = name
      this.operatorCrew = crew
      this.operatorRole = role
    },
  },
})
