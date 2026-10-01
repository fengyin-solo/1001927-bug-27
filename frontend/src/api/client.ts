/** 统一请求封装：拼后端地址、注入当前值班身份、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const session = useSessionStore()
  // HTTP 头只允许 Latin-1 字符，中文姓名/班组需百分号编码，后端 unquote 还原
  const identityHeaders: Record<string, string> = {
    'X-Operator': encodeURIComponent(session.operator),
    'X-Operator-Crew': encodeURIComponent(session.operatorCrew),
    'X-Operator-Role': encodeURIComponent(session.operatorRole),
  }
  return fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...identityHeaders,
      ...(init?.headers ?? {}),
    },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
