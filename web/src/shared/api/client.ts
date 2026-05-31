import createClient from 'openapi-fetch'
import type { paths } from './schema'

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const openapiClient = createClient<paths>({ baseUrl: API_URL })
export const AUTH_TOKEN_STORAGE_KEY = 'newscope.auth.access_token'

export function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
}

export function setStoredAccessToken(token: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
}

export function clearStoredAccessToken(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
}

async function responseErrorMessage(response: Response): Promise<string> {
  const text = await response.text()
  if (!text) return `HTTP ${response.status}`
  try {
    const data = JSON.parse(text) as { detail?: unknown; message?: unknown }
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
          return JSON.stringify(item)
        })
        .join('; ')
    }
    if (typeof data.message === 'string') return data.message
  } catch {
    // Plain-text responses are shown as-is.
  }
  return text
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredAccessToken()
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response))
  }
  return response.json() as Promise<T>
}

export type AuthUser = {
  id: number
  username: string
  email?: string | null
  is_admin: boolean
  created_at: string
  last_active_at?: string | null
}
export type AuthTokenResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}
export type AuthRegisterPayload = {
  username: string
  email?: string | null
  password: string
}
export type AuthLoginPayload = {
  login: string
  password: string
}

export type NewsSummary = {
  id: number
  title: string
  snippet?: string
  source: { id: number; name: string; type: string }
  url: string
  published_at?: string
  ingested_at: string
  content_grade: number
  information_type: string
  urgency: string
  is_uncertain: boolean
  processed: boolean
  topics: Array<{ id: number; name: string }>
  entities: Array<{ id: number; name: string; type: string }>
}

export type NewsDetail = NewsSummary & {
  content?: string
  canonical_url: string
  language: string
  content_status: string
  event_cluster_id?: number
  chunk_count: number
  extra: Record<string, unknown>
}

export type FeedResponse = { items: NewsSummary[]; meta: { total: number; limit: number; offset: number } }
export type FeedFilters = {
  limit?: number
  offset?: number
  sourceId?: number | null
  sourceIds?: number[] | null
  topic?: string | null
  contentGradeMax?: number | null
  processedOnly?: boolean
  personalized?: boolean
}
export type SourceFilter = NewsSummary['source'] & {
  news_count: number
  processed_count: number
}
export type TopicFilter = {
  id: number
  name: string
  news_count: number
}
export type SearchResponse = {
  query: string
  corrected_query?: string
  intent: string
  total: number
  search_time_ms: number
  results: Array<{
    news_id: number
    title: string
    snippet: string
    source_name: string
    personalized_score: number
    base_score: number
    retrieval_mode?: string
    explanation?: string
    topics: string[]
    entities: string[]
    content_grade: number
  }>
}
export type ChatResponse = {
  session_id?: number
  answer: string
  confidence: string
  rag_mode: string
  model_name: string
  generation_log_id?: number
  sources: Array<{ news_id: number; source_name: string; title: string; url?: string | null }>
}
export type DigestResponse = {
  id: number
  digest_type: string
  content_text: string
  news_count: number
  generated_at: string
  topics_covered: string[]
  items: Array<{ news_id: number; position: number; title?: string; snippet?: string | null; url?: string | null }>
}
export type ProfileResponse = {
  profile: {
    user_id: number
    username: string
    email?: string | null
    settings: Record<string, unknown>
  }
  topic_weights: Array<{ topic_id: number; name?: string | null; weight: number }>
  entity_weights: Array<{ entity_id: number; name?: string | null; weight: number }>
  entity_subscriptions: Array<{ entity_id: number; name?: string | null; alert_on_spike: boolean; alert_on_news: boolean }>
  tracked_keywords: Array<{ keyword: string }>
  source_preferences: Array<{ source_id: number; name?: string | null; preference: string }>
}
export type PreferencePayload = {
  profile: {
    user_id?: number
    username?: string
    email?: string | null
    settings?: Record<string, unknown>
  }
  topic_weights?: Array<{ topic_id: number; weight: number }>
  entity_weights?: Array<{ entity_id: number; weight: number }>
  entity_subscriptions?: Array<{ entity_id: number; alert_on_spike: boolean; alert_on_news: boolean }>
  tracked_keywords?: Array<{ keyword: string }>
  source_preferences?: Array<{ source_id: number; preference: string }>
}
export type AdminUserItem = {
  id: number
  username: string
  email?: string | null
  is_admin: boolean
  has_password: boolean
  created_at: string
  last_active_at?: string | null
  chat_sessions: number
  interactions: number
  digests: number
  search_logs: number
  generation_logs: number
}
export type AdminUsersResponse = {
  items: AdminUserItem[]
  total: number
  admin_count: number
}
export type AdminSettingsResponse = {
  auth: Record<string, unknown>
  runtime: Record<string, unknown>
  retrieval: Record<string, unknown>
  llm: Record<string, unknown>
  celery: Record<string, unknown>
}

function toQuery(params: Record<string, string | number | boolean | Array<string | number> | null | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)))
      return
    }
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}

export const api = {
  register: (payload: AuthRegisterPayload) =>
    request<AuthTokenResponse>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  login: (payload: AuthLoginPayload) =>
    request<AuthTokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  me: () => request<AuthUser>('/api/v1/auth/me'),
  logout: () => request<{ logged_out: boolean }>('/api/v1/auth/logout', { method: 'POST' }),
  feed: (filters: FeedFilters = {}) =>
    request<FeedResponse>(
      `/api/v1/news/feed${toQuery({
        limit: filters.limit ?? 20,
        offset: filters.offset ?? 0,
        source_id: filters.sourceId,
        source_ids: filters.sourceIds ?? undefined,
        topic: filters.topic,
        content_grade_max: filters.contentGradeMax,
        processed_only: filters.processedOnly,
        personalized: filters.personalized,
      })}`,
    ),
  sources: () => request<{ items: SourceFilter[] }>('/api/v1/news/sources'),
  topics: () => request<{ items: TopicFilter[] }>('/api/v1/news/topics'),
  news: (id: string | number) => request<NewsDetail>(`/api/v1/news/${id}`),
  search: (query: string) =>
    request<SearchResponse>('/api/v1/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit: 10 }),
    }),
  chat: (message: string, sessionId?: number) =>
    request<ChatResponse>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message, session_id: sessionId, mode: 'standard', limit: 8 }),
    }),
  chatSessions: () => request<{ items: Array<{ id: number; title?: string; message_count: number }> }>('/api/v1/chat/sessions'),
  chatMessages: (id: string | number) => request<{ messages: Array<{ role: string; content: string }> }>(`/api/v1/chat/sessions/${id}/messages`),
  feedback: (newsId: number, action: string) =>
    request<{ recorded: boolean; interaction_id: number; stored_action: string; derived_signal: number }>(
      '/api/v1/feedback',
      {
        method: 'POST',
        body: JSON.stringify({ news_id: newsId, action }),
      },
    ),
  profile: () => request<ProfileResponse>('/api/v1/profile'),
  updateProfile: (payload: PreferencePayload) =>
    request<ProfileResponse>('/api/v1/profile/preferences', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  interactions: () => request<any>('/api/v1/profile/interactions?limit=12'),
  digest: () => request<DigestResponse>('/api/v1/digest'),
  generateDigest: (query?: string, topics: string[] = [], periodHours?: number) =>
    request<DigestResponse>('/api/v1/digest/generate', {
      method: 'POST',
      body: JSON.stringify({
        force: true,
        query: query || 'главные новости сегодня',
        topics,
        period_hours: periodHours,
        digest_style: 'editorial',
      }),
    }),
  adminOverview: () => request<any>('/api/v1/admin/overview'),
  adminSources: () => request<any>('/api/v1/admin/sources'),
  adminProcessing: () => request<any>('/api/v1/admin/processing'),
  adminSearch: () => request<any>('/api/v1/admin/search-stats'),
  adminGeneration: () => request<any>('/api/v1/admin/generation-stats'),
  adminUsers: () => request<AdminUsersResponse>('/api/v1/admin/users'),
  updateAdminUser: (id: number, isAdmin: boolean) =>
    request<AdminUserItem>(`/api/v1/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_admin: isAdmin }),
    }),
  adminSettings: () => request<AdminSettingsResponse>('/api/v1/admin/settings'),
}
