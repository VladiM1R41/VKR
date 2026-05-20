import { useQuery } from '@tanstack/react-query'

import { api } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock, LoadingBlock } from '../shared/ui/State'

function StatCard({ title, value, hint }: { title: string; value: unknown; hint?: string }) {
  return (
    <div className="panel rounded-3xl p-5">
      <p className="label">{title}</p>
      <p className="mt-2 font-display text-4xl font-bold">{String(value ?? '—')}</p>
      {hint && <p className="mt-2 text-sm text-ink/55">{hint}</p>}
    </div>
  )
}

function StatusPill({ value }: { value: string }) {
  const ok = value === 'ok' || value === 'green' || value === 'healthy'
  return (
    <span className={`rounded-full px-3 py-1 text-xs ${ok ? 'bg-blue-50 text-[#2563eb]' : 'bg-sky-50 text-[#0ea5e9]'}`}>
      {value}
    </span>
  )
}

export function AdminPage() {
  const overview = useQuery({ queryKey: queryKeys.adminOverview, queryFn: api.adminOverview })
  const sources = useQuery({ queryKey: ['admin', 'sources'], queryFn: api.adminSources })
  const processing = useQuery({ queryKey: ['admin', 'processing'], queryFn: api.adminProcessing })
  const search = useQuery({ queryKey: ['admin', 'search'], queryFn: api.adminSearch })
  const generation = useQuery({ queryKey: ['admin', 'generation'], queryFn: api.adminGeneration })

  if (overview.isLoading) return <LoadingBlock label="Собираю состояние системы..." />
  if (overview.error) return <ErrorBlock error={overview.error} />

  const corpus = overview.data?.corpus ?? {}
  const infra = overview.data?.infrastructure ?? {}
  const sourceItems = sources.data?.items ?? []
  const unhealthySources = sourceItems.filter((item: any) => item.health_status !== 'healthy' && item.health_status !== 'ok')

  return (
    <section>
      <p className="label">Администрирование</p>
      <h1 className="font-display text-5xl font-bold">Панель состояния Newscope</h1>
      <p className="mt-3 max-w-3xl text-ink/65">
        Здесь собраны быстрые признаки здоровья слоёв 1-5: корпус, обработка, индекс, поиск, генерация и источники.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Всего новостей" value={corpus.news_total} />
        <StatCard title="Обработано" value={corpus.news_processed} hint={`${corpus.news_unprocessed ?? 0} ждут обработки`} />
        <StatCard title="Чанков в БД" value={corpus.chunks} />
        <StatCard title="Источники" value={`${corpus.sources_active ?? 0}/${corpus.sources_total ?? 0}`} hint="активные / всего" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="panel rounded-[2rem] p-6">
          <p className="label">Инфраструктура</p>
          <h2 className="font-display text-3xl font-bold">Готовность хранилищ</h2>
          <div className="mt-4 space-y-3">
            {Object.entries(infra).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between rounded-2xl border border-blue-50 bg-white p-3">
                <span className="font-semibold">{key}</span>
                <StatusPill value={String(value)} />
              </div>
            ))}
          </div>
        </div>

        <div className="panel rounded-[2rem] p-6">
          <p className="label">Обработка и индекс</p>
          <h2 className="font-display text-3xl font-bold">PostgreSQL ↔ Qdrant</h2>
          {processing.isLoading && <LoadingBlock />}
          {processing.data && (
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <StatCard title="processed" value={processing.data.processed} />
              <StatCard title="pending" value={processing.data.unprocessed} />
              <StatCard
                title="Qdrant"
                value={processing.data.qdrant?.is_green ? 'green' : processing.data.qdrant?.status ?? 'check'}
              />
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <div className="panel rounded-[2rem] p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="label">Источники</p>
              <h2 className="font-display text-3xl font-bold">Здоровье сбора</h2>
            </div>
            <StatusPill value={unhealthySources.length ? `${unhealthySources.length} требуют внимания` : 'healthy'} />
          </div>
          <div className="mt-4 max-h-96 overflow-auto">
            <table className="w-full border-separate border-spacing-y-2 text-sm">
              <thead className="text-left text-ink/55">
                <tr>
                  <th>Источник</th>
                  <th>Статус</th>
                  <th>Ошибки</th>
                  <th>Извлечение</th>
                </tr>
              </thead>
              <tbody>
                {sourceItems.map((item: any) => (
                  <tr key={item.id} className="bg-white">
                    <td className="rounded-l-2xl p-3 font-semibold">{item.name}</td>
                    <td className="p-3">
                      <StatusPill value={item.health_status ?? 'unknown'} />
                    </td>
                    <td className="p-3">{item.consecutive_failures ?? 0}</td>
                    <td className="rounded-r-2xl p-3">
                      {item.extraction_success_rate == null ? '—' : `${Math.round(item.extraction_success_rate * 100)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="grid gap-6">
          <div className="panel rounded-[2rem] p-6">
            <p className="label">Поиск</p>
            <h2 className="font-display text-3xl font-bold">Последние запросы</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <StatCard title="Всего" value={search.data?.total_searches} />
              <StatCard title="Средняя задержка" value={search.data?.avg_latency_ms ? `${Math.round(search.data.avg_latency_ms)} ms` : '—'} />
              <StatCard title="Cache hit" value={search.data?.cache_hit_count} />
            </div>
            <div className="mt-4 space-y-2">
              {search.data?.recent_queries?.slice(0, 5).map((item: any) => (
                <div key={item.id} className="rounded-2xl border border-blue-50 bg-white p-3 text-sm">
                  <strong>{item.query}</strong>
                  <div className="mt-1 text-ink/55">
                    {item.retrieval_mode} · {item.latency_ms} ms · {item.cache_hit ? 'cache' : 'live'}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel rounded-[2rem] p-6">
            <p className="label">Генерация</p>
            <h2 className="font-display text-3xl font-bold">RAG и LLM</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <StatCard title="Всего" value={generation.data?.total_generations} />
              <StatCard
                title="Средняя задержка"
                value={generation.data?.avg_latency_ms ? `${Math.round(generation.data.avg_latency_ms)} ms` : '—'}
              />
              <StatCard title="Режимы" value={Object.keys(generation.data?.rag_modes ?? {}).length} />
            </div>
            <div className="mt-4 space-y-2">
              {generation.data?.recent_generations?.slice(0, 5).map((item: any) => (
                <div key={item.id} className="rounded-2xl border border-blue-50 bg-white p-3 text-sm">
                  <strong>{item.query || 'generation'}</strong>
                  <div className="mt-1 text-ink/55">
                    {item.rag_mode} · {item.model_name} · {item.confidence} · {item.latency_ms} ms
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
