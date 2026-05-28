import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'

import { api } from '../shared/api/client'
import type { PreferencePayload, ProfileResponse, TopicFilter } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock, LoadingBlock } from '../shared/ui/State'

function basePayload(data: ProfileResponse, settings: Record<string, unknown>): PreferencePayload {
  return {
    profile: {
      user_id: data.profile.user_id,
      username: data.profile.username,
      email: data.profile.email,
      settings,
    },
    topic_weights: data.topic_weights.map((item) => ({ topic_id: item.topic_id, weight: item.weight })),
    entity_weights: data.entity_weights.map((item) => ({ entity_id: item.entity_id, weight: item.weight })),
    entity_subscriptions: data.entity_subscriptions.map((item) => ({
      entity_id: item.entity_id,
      alert_on_spike: item.alert_on_spike,
      alert_on_news: item.alert_on_news,
    })),
    tracked_keywords: data.tracked_keywords.map((item) => ({ keyword: item.keyword })),
    source_preferences: data.source_preferences.map((item) => ({ source_id: item.source_id, preference: item.preference })),
  }
}

function looksLikeLegacyDigest(text: string | undefined): boolean {
  if (!text) return false
  const normalized = text.toLowerCase()
  return (
    normalized.includes('исправь предыдущий ответ') ||
    normalized.includes('strict rag') ||
    normalized.includes('предыдущий ответ') ||
    normalized.includes('prompt')
  )
}

function stripDigestSourcesBlock(text: string): string {
  return text.replace(/\n\s*(?:#{1,4}\s*)?(?:[📝]\s*)?\**Источники:?\**[\s\S]*$/i, '').trim()
}

function compactTitle(title: string | undefined, maxLength = 42): string {
  const clean = (title || '').replace(/\s+/g, ' ').trim()
  if (!clean) return 'источник'
  return clean.length > maxLength ? `${clean.slice(0, maxLength - 1).trim()}…` : clean
}

export function DigestPage() {
  const queryClient = useQueryClient()
  const digest = useQuery({ queryKey: queryKeys.digest(), queryFn: api.digest })
  const profile = useQuery({ queryKey: queryKeys.profile, queryFn: api.profile })
  const topics = useQuery({ queryKey: queryKeys.topics, queryFn: api.topics })
  const [time, setTime] = useState('09:00')
  const [periodHours, setPeriodHours] = useState(24)
  const [selectedTopics, setSelectedTopics] = useState<string[]>([])

  useEffect(() => {
    const settings = profile.data?.profile.settings
    if (!settings) return
    setTime(String(settings.digest_time ?? '09:00'))
    setPeriodHours(Number(settings.digest_period_hours ?? 24))
    setSelectedTopics(Array.isArray(settings.digest_topics) ? settings.digest_topics.map(String) : [])
  }, [profile.data])

  const digestQuery = useMemo(() => {
    const theme = selectedTopics.length ? selectedTopics.join(', ') : 'главные новости'
    return `${theme} за последние ${periodHours} часов`
  }, [periodHours, selectedTopics])

  const saveSettings = useMutation({
    mutationFn: () => {
      if (!profile.data) throw new Error('Профиль ещё не загружен')
      return api.updateProfile(
        basePayload(profile.data, {
          ...(profile.data.profile.settings ?? {}),
          digest_time: time,
          digest_period_hours: periodHours,
          digest_topics: selectedTopics,
        }),
      )
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.profile }),
  })

  const generate = useMutation({
    mutationFn: () => api.generateDigest(digestQuery, selectedTopics, periodHours),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.digest() }),
  })
  const digestText = digest.data?.content_text ?? ''
  const digestBodyText = stripDigestSourcesBlock(digestText)
  const sourceButtons = digest.data?.items?.slice(0, 10) ?? []
  const legacyDigest = looksLikeLegacyDigest(digestText)

  if (digest.isLoading) return <LoadingBlock label="Загружаю дайджест..." />
  if (digest.error) return <ErrorBlock error={digest.error} />

  return (
    <section className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <aside className="panel h-fit rounded-[2rem] p-6">
        <p className="label">Настройки дайджеста</p>
        <h1 className="font-display text-4xl font-bold">Персональная сводка</h1>
        <p className="mt-2 text-sm text-ink/60">
          Настройки сохраняются в профиле и используются для ручной генерации. Автоматическая доставка будет
          следующим шагом, когда добавим полноценный планировщик Layer 6.
        </p>

        <label className="mt-6 block">
          <span className="text-sm font-semibold">Время отправки</span>
          <input
            type="time"
            value={time}
            onChange={(event) => setTime(event.target.value)}
            className="mt-2 w-full rounded-2xl border border-blue-100 bg-white p-3 outline-none focus:border-[#2563eb]"
          />
        </label>

        <label className="mt-4 block">
          <span className="text-sm font-semibold">Период новостей</span>
          <select
            value={periodHours}
            onChange={(event) => setPeriodHours(Number(event.target.value))}
            className="mt-2 w-full rounded-2xl border border-blue-100 bg-white p-3 outline-none focus:border-[#2563eb]"
          >
            <option value={12}>последние 12 часов</option>
            <option value={24}>последние 24 часа</option>
            <option value={72}>последние 3 дня</option>
            <option value={168}>последняя неделя</option>
          </select>
        </label>

        <div className="mt-5">
          <p className="mb-3 text-sm font-semibold">Темы дайджеста</p>
          <div className="flex flex-wrap gap-2">
            {topics.data?.items.slice(0, 14).map((topic: TopicFilter) => {
              const active = selectedTopics.includes(topic.name)
              return (
                <button
                  key={topic.id}
                  type="button"
                  onClick={() =>
                    setSelectedTopics((current) =>
                      current.includes(topic.name)
                        ? current.filter((item) => item !== topic.name)
                        : [...current, topic.name],
                    )
                  }
                  className={`rounded-full px-3 py-2 text-xs ${
                    active ? 'bg-[#2563eb] text-white' : 'bg-white hover:bg-blue-50'
                  }`}
                >
                  {topic.name}
                </button>
              )
            })}
          </div>
        </div>

        <div className="mt-6 space-y-3">
          <button
            onClick={() => saveSettings.mutate()}
            className="w-full rounded-full bg-white px-5 py-3 font-semibold text-ink hover:bg-paper"
          >
            {saveSettings.isPending ? 'Сохраняю...' : 'Сохранить настройки'}
          </button>
          <button
            onClick={() => generate.mutate()}
            className="w-full rounded-full bg-[#2563eb] px-5 py-3 font-semibold text-white hover:bg-[#1d4ed8]"
          >
            {generate.isPending ? 'Генерирую...' : 'Собрать дайджест сейчас'}
          </button>
        </div>
      </aside>

      <div className="panel rounded-[2rem] p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="label">Последний дайджест</p>
            <h2 className="font-display text-5xl font-bold">Сводка по выбранному контексту</h2>
            <p className="mt-2 text-sm text-ink/55">Запрос генерации: {digestQuery}</p>
          </div>
          <div className="rounded-2xl border border-blue-100 bg-white p-4 text-sm">
            <div>Новостей: {digest.data?.news_count ?? 0}</div>
            <div>
              Сгенерирован:{' '}
              {digest.data?.generated_at ? new Date(digest.data.generated_at).toLocaleString('ru-RU') : '—'}
            </div>
          </div>
        </div>

        {legacyDigest && (
          <div className="mt-8 rounded-3xl border border-copper/25 bg-copper/10 p-5 text-sm text-ink/75">
            <strong className="block text-ink">В сохранённом дайджесте найден старый тестовый текст.</strong>
            <span>
              Это не ошибка текущего интерфейса: в базе осталась прежняя генерация. Нажмите «Собрать дайджест сейчас»,
              чтобы получить новую сводку по актуальным настройкам.
            </span>
          </div>
        )}

        <p className={`mt-8 whitespace-pre-wrap text-lg leading-8 ${legacyDigest ? 'text-ink/55' : ''}`}>
          {digestBodyText || digestText || 'Дайджест пока не сформирован.'}
        </p>

        {!!sourceButtons.length && (
          <div className="mt-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-display text-2xl font-bold">Источники</h3>
              {!!digest.data?.items?.length && digest.data.items.length > sourceButtons.length && (
                <span className="text-sm text-ink/55">
                  показаны первые {sourceButtons.length} из {digest.data.items.length}
                </span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {sourceButtons.map((item) => {
                const label = `#${item.position} ${compactTitle(item.title)}`
                const className =
                  'max-w-[260px] truncate rounded-full border border-blue-100 bg-white px-3 py-2 text-sm font-semibold text-ink shadow-sm hover:border-[#2563eb] hover:text-[#2563eb]'
                return item.url ? (
                  <a
                    key={`${item.news_id}-${item.position}`}
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    title={item.title || `news ${item.news_id}`}
                    className={className}
                  >
                    {label}
                  </a>
                ) : (
                  <Link
                    key={`${item.news_id}-${item.position}`}
                    to={`/news/${item.news_id}`}
                    title={item.title || `news ${item.news_id}`}
                    className={className}
                  >
                    {label}
                  </Link>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
