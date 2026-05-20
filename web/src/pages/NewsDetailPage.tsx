import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { API_URL, api } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock, LoadingBlock } from '../shared/ui/State'

const feedbackLabels: Record<string, string> = {
  like: 'Полезно',
  save: 'Сохранить',
  hide: 'Скрыть',
}

export function NewsDetailPage() {
  const { newsId = '' } = useParams()
  const queryClient = useQueryClient()
  const news = useQuery({ queryKey: queryKeys.news(newsId), queryFn: () => api.news(newsId), enabled: Boolean(newsId) })
  const feedback = useMutation({
    mutationFn: async (action: string) => {
      await fetch(`${API_URL}/api/v1/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: Number(newsId), action }),
      })
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.profile }),
  })

  if (news.isLoading) return <LoadingBlock />
  if (news.error) return <ErrorBlock error={news.error} />
  if (!news.data) return null

  return (
    <article className="mx-auto max-w-5xl">
      <Link to="/" className="text-sm text-moss hover:text-copper">
        ← Назад к ленте
      </Link>
      <div className="panel mt-5 rounded-[2rem] p-8 md:p-10">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="label">
            {news.data.source.name} · grade {news.data.content_grade} · {news.data.information_type}
          </div>
          <a
            href={news.data.url || news.data.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-full bg-[#2563eb] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#1d4ed8]"
          >
            В источнике
          </a>
        </div>
        <h1 className="font-display text-4xl font-black leading-tight md:text-6xl">{news.data.title}</h1>
        <div className="mt-5 flex flex-wrap gap-2">
          {news.data.topics.map((topic) => (
            <span key={topic.id} className="rounded-full bg-blue-50 px-3 py-1 text-sm text-[#2563eb]">
              {topic.name}
            </span>
          ))}
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          {Object.entries(feedbackLabels).map(([action, label]) => (
            <button
              key={action}
              onClick={() => feedback.mutate(action)}
              className="rounded-full border border-blue-200 bg-white px-4 py-2 hover:bg-[#2563eb] hover:text-white"
            >
              {label}
            </button>
          ))}
        </div>
        <p className="mt-8 whitespace-pre-wrap text-lg leading-8 text-ink/80">{news.data.content || news.data.snippet}</p>
        <div className="mt-10 rounded-3xl border border-blue-100 bg-blue-50/70 p-5 text-sm text-ink/70">
          <strong className="block text-ink">Оригинал статьи в первоисточнике</strong>
          <span>{news.data.source.name}: </span>
          <a
            href={news.data.url || news.data.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="break-all font-semibold text-moss hover:text-ink"
          >
            {news.data.url || news.data.canonical_url}
          </a>
        </div>
      </div>
    </article>
  )
}
