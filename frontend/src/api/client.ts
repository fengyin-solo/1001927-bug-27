/** 统一请求封装：拼后端地址、带当前登录身份、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function authHeaders(): Record<string, string> {
  // 会话 store 在 pinia 安装后即可使用；组件外调用时走惰性获取
  const session = useSessionStore()
  return {
    'X-Operator-Name': encodeURIComponent(session.operator),
    'X-Operator-Team': encodeURIComponent(session.team),
    'X-Operator-Role': encodeURIComponent(session.role),
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers ?? {}) },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 读取接口错误说明：优先展示后端返回的 403/409 中文原因。 */
export async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string }
    if (payload.detail) {
      return payload.detail
    }
  } catch {
    // 非 JSON 错误体时用兜底文案
  }
  return fallback
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
