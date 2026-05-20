export const queryKeys = {
  feed: (filters?: unknown) => ['news', 'feed', filters] as const,
  sources: ['news', 'sources'] as const,
  topics: ['news', 'topics'] as const,
  news: (id: string | number) => ['news', id] as const,
  search: (query: string) => ['search', query] as const,
  chatSessions: ['chat', 'sessions'] as const,
  chatMessages: (id: string | number) => ['chat', id, 'messages'] as const,
  profile: ['profile'] as const,
  digest: (type = 'on_demand') => ['digest', type] as const,
  adminOverview: ['admin', 'overview'] as const,
}
