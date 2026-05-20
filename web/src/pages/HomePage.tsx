import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { NewsCard } from '../features/news/NewsCard'
import { groupSources } from '../features/news/sourceGroups'
import { SearchBox } from '../features/search/SearchBox'
import { api } from '../shared/api/client'
import type { TopicFilter } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock, LoadingBlock } from '../shared/ui/State'

function FilterButton({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-2xl px-4 py-3 text-left text-sm transition ${
        active ? 'bg-[#2563eb] text-white shadow-panel' : 'bg-white text-ink/75 hover:bg-blue-50'
      }`}
    >
      {children}
    </button>
  )
}

export function HomePage() {
  const [query, setQuery] = useState('')
  const [sourceGroupKey, setSourceGroupKey] = useState<string | null>(null)
  const [topic, setTopic] = useState<string | null>(null)
  const [processedOnly, setProcessedOnly] = useState(false)
  const [personalizedFeed, setPersonalizedFeed] = useState(true)

  const sources = useQuery({ queryKey: queryKeys.sources, queryFn: api.sources })
  const topics = useQuery({ queryKey: queryKeys.topics, queryFn: api.topics })
  const sourceGroups = useMemo(() => groupSources(sources.data?.items ?? []), [sources.data])
  const selectedSource = sourceGroups.find((item) => item.key === sourceGroupKey)

  const feedFilters = useMemo(
    () => ({
      limit: 24,
      sourceIds: selectedSource?.ids ?? null,
      topic,
      processedOnly,
      personalized: personalizedFeed,
    }),
    [selectedSource, topic, processedOnly, personalizedFeed],
  )
  const feed = useQuery({ queryKey: queryKeys.feed(feedFilters), queryFn: () => api.feed(feedFilters) })
  const search = useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => api.search(query),
    enabled: query.length > 0,
  })

  return (
    <section className="news-bg relative left-1/2 -ml-[50vw] -my-8 min-h-screen w-screen px-6 py-10 xl:px-10">
      <div className="mx-auto max-w-[1580px]">
        <div className="mb-10 grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
          <div>
            <p className="label mb-3">Мониторинг электронных СМИ</p>
            <h1 className="font-display text-5xl font-black leading-none md:text-7xl">
              Лента, поиск и ответы по корпусу новостей в одном рабочем месте.
            </h1>
          </div>
          <div className="rounded-[2rem] bg-[#2563eb] p-6 text-white shadow-panel">
            <p className="text-lg text-white/90">
              Здесь можно проверить весь конвейер: новости собираются, обрабатываются, ищутся,
              персонализируются и используются как контекст для генерации ответов.
            </p>
          </div>
        </div>

        <SearchBox onSearch={setQuery} isLoading={search.isFetching} />

        {query && (
          <div className="mt-8">
            <h2 className="mb-4 font-display text-3xl font-bold">Результаты поиска</h2>
            {search.isLoading && <LoadingBlock label="Идёт гибридный поиск..." />}
            {search.error && <ErrorBlock error={search.error} />}
            <div className="grid gap-4">
              {search.data?.results.map((item) => (
                <Link key={item.news_id} to={`/news/${item.news_id}`} className="panel rounded-3xl p-5 hover:border-copper/50">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-moss">
                    <span>{item.source_name}</span>
                    <span>score {item.personalized_score.toFixed(3)}</span>
                    {item.retrieval_mode && <span>{item.retrieval_mode}</span>}
                  </div>
                  <h3 className="font-display text-2xl font-bold">{item.title}</h3>
                  <p className="mt-2 text-ink/70">{item.snippet}</p>
                  {item.explanation && <p className="mt-3 text-xs text-ink/50">{item.explanation}</p>}
                </Link>
              ))}
            </div>
          </div>
        )}

        <div className="mt-10 grid gap-7 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[330px_minmax(0,1fr)]">
          <aside className="panel h-fit rounded-[2rem] p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="label">Фильтры ленты</p>
                <h2 className="font-display text-2xl font-bold">Источники и темы</h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSourceGroupKey(null)
                  setTopic(null)
                  setProcessedOnly(false)
                  setPersonalizedFeed(true)
                }}
                className="rounded-full bg-blue-50 px-3 py-2 text-xs text-[#1d4ed8] hover:bg-blue-100"
              >
                Сбросить
              </button>
            </div>

            <label className="mt-5 flex items-center gap-3 rounded-2xl border border-blue-50 bg-white p-3 text-sm">
              <input
                type="checkbox"
                checked={processedOnly}
                onChange={(event) => setProcessedOnly(event.target.checked)}
              />
              Показывать только обработанные новости
            </label>

            <label className="mt-3 flex items-center gap-3 rounded-2xl border border-blue-50 bg-white p-3 text-sm">
              <input
                type="checkbox"
                checked={personalizedFeed}
                onChange={(event) => setPersonalizedFeed(event.target.checked)}
              />
              Учитывать профиль: скрывать источники «Скрыть»
            </label>

            <div className="mt-5">
              <p className="mb-3 text-sm font-semibold text-ink/70">Источник</p>
              <div className="max-h-80 space-y-2 overflow-auto pr-1">
                <FilterButton active={sourceGroupKey === null} onClick={() => setSourceGroupKey(null)}>
                  Все источники
                </FilterButton>
                {sourceGroups.map((source) => (
                  <FilterButton key={source.key} active={sourceGroupKey === source.key} onClick={() => setSourceGroupKey(source.key)}>
                    <span className="flex items-center justify-between gap-3">
                      <span>{source.name}</span>
                      <span className="text-xs opacity-70">{source.news_count}</span>
                    </span>
                    {source.sources.length > 1 && (
                      <span className="mt-1 block text-xs opacity-60">{source.sources.length} RSS-ленты</span>
                    )}
                  </FilterButton>
                ))}
              </div>
            </div>

            <div className="mt-5">
              <p className="mb-3 text-sm font-semibold text-ink/70">Тематика</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setTopic(null)}
                  className={`rounded-full px-3 py-2 text-xs ${topic === null ? 'bg-[#2563eb] text-white' : 'bg-white hover:bg-blue-50'}`}
                >
                  Все
                </button>
                {topics.data?.items.slice(0, 16).map((item: TopicFilter) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setTopic(item.name)}
                    className={`rounded-full px-3 py-2 text-xs ${
                      topic === item.name ? 'bg-[#2563eb] text-white' : 'bg-white hover:bg-blue-50'
                    }`}
                  >
                    {item.name} · {item.news_count}
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <div>
            <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="label">Свежая лента</p>
                <h2 className="font-display text-3xl font-bold">
                  {selectedSource ? `Новости источника «${selectedSource.name}»` : 'Все новости'}
                </h2>
              </div>
              <p className="text-sm text-ink/55">
                Найдено: {feed.data?.meta.total ?? '...'}
                {topic ? ` · тема: ${topic}` : ''}
                {personalizedFeed ? ' · профиль включён' : ' · все источники'}
              </p>
            </div>
            {feed.isLoading && <LoadingBlock />}
            {feed.error && <ErrorBlock error={feed.error} />}
            <div className="grid gap-4">
              {feed.data?.items.map((item) => <NewsCard key={item.id} item={item} />)}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
