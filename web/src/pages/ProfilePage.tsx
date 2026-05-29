import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { groupSources } from '../features/news/sourceGroups'
import { api } from '../shared/api/client'
import type { PreferencePayload, ProfileResponse, TopicFilter } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock, LoadingBlock } from '../shared/ui/State'

type SourcePreference = 'preferred' | 'neutral' | 'blocked'

function preserveProfilePayload(data: ProfileResponse, settings: Record<string, unknown>): PreferencePayload {
  return {
    profile: {
      user_id: data.profile.user_id,
      username: data.profile.username,
      email: data.profile.email,
      settings,
    },
    entity_weights: data.entity_weights.map((item) => ({ entity_id: item.entity_id, weight: item.weight })),
    entity_subscriptions: data.entity_subscriptions.map((item) => ({
      entity_id: item.entity_id,
      alert_on_spike: item.alert_on_spike,
      alert_on_news: item.alert_on_news,
    })),
  }
}

function groupPreference(sourceIds: number[], prefs: Record<number, SourcePreference>): SourcePreference {
  const values = sourceIds.map((id) => prefs[id] ?? 'neutral')
  if (values.every((item) => item === 'preferred')) return 'preferred'
  if (values.every((item) => item === 'blocked')) return 'blocked'
  return 'neutral'
}

function sourcePreferenceLabel(preference: SourcePreference): string {
  if (preference === 'preferred') return 'Люблю'
  if (preference === 'blocked') return 'Скрыть'
  return 'Нейтрально'
}

export function ProfilePage() {
  const queryClient = useQueryClient()
  const profile = useQuery({ queryKey: queryKeys.profile, queryFn: api.profile })
  const topics = useQuery({ queryKey: queryKeys.topics, queryFn: api.topics })
  const sources = useQuery({ queryKey: queryKeys.sources, queryFn: api.sources })

  const [diversity, setDiversity] = useState(0.3)
  const [topicWeights, setTopicWeights] = useState<Record<number, number>>({})
  const [sourcePrefs, setSourcePrefs] = useState<Record<number, SourcePreference>>({})

  useEffect(() => {
    if (!profile.data) return
    const settings = profile.data.profile.settings ?? {}
    setDiversity(Number(settings.diversity_slider ?? 0.3))
    setTopicWeights(Object.fromEntries(profile.data.topic_weights.map((item) => [item.topic_id, item.weight])))
    setSourcePrefs(
      Object.fromEntries(profile.data.source_preferences.map((item) => [item.source_id, item.preference as SourcePreference])),
    )
  }, [profile.data])

  const save = useMutation({
    mutationFn: (payload: PreferencePayload) => api.updateProfile(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.profile })
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot })
      queryClient.invalidateQueries({ queryKey: queryKeys.search('') })
    },
  })

  const topicCatalog = useMemo(() => topics.data?.items.slice(0, 12) ?? [], [topics.data])
  const sourceCatalog = useMemo(() => groupSources(sources.data?.items ?? []), [sources.data])

  if (profile.isLoading) return <LoadingBlock />
  if (profile.error) return <ErrorBlock error={profile.error} />
  if (!profile.data) return null

  const selectedTopicsCount = Object.values(topicWeights).filter((value) => value > 0).length
  const preferredSourcesCount = Object.values(sourcePrefs).filter((item) => item === 'preferred').length
  const blockedSourcesCount = Object.values(sourcePrefs).filter((item) => item === 'blocked').length

  const setSourceGroupPreference = (sourceIds: number[], preference: SourcePreference) => {
    setSourcePrefs((current) => {
      const next = { ...current }
      sourceIds.forEach((sourceId) => {
        next[sourceId] = preference
      })
      return next
    })
  }

  const submit = () => {
    const settings = {
      ...(profile.data.profile.settings ?? {}),
      diversity_slider: Number(diversity.toFixed(2)),
    }

    save.mutate({
      ...preserveProfilePayload(profile.data, settings),
      topic_weights: Object.entries(topicWeights)
        .map(([topic_id, weight]) => ({ topic_id: Number(topic_id), weight: Number(weight) }))
        .filter((item) => item.weight > 0),
      source_preferences: Object.entries(sourcePrefs).map(([source_id, preference]) => ({
        source_id: Number(source_id),
        preference,
      })),
      tracked_keywords: profile.data.tracked_keywords.map((item) => ({ keyword: item.keyword })),
    })
  }

  return (
    <section className="space-y-6">
      <div className="panel overflow-hidden rounded-[2.25rem]">
        <div className="relative isolate p-6 md:p-8">
          <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_left,rgba(37,99,235,0.18),transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.96),rgba(234,243,255,0.86))]" />
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-3xl bg-[#2563eb] font-display text-3xl font-bold text-white shadow-soft">
                {(profile.data.profile.username || 'U').slice(0, 1).toUpperCase()}
              </div>
              <div>
                <p className="label">Профиль пользователя</p>
                <h1 className="font-display text-4xl font-bold">{profile.data.profile.username}</h1>
                <p className="mt-1 text-sm text-ink/60">
                  Пользователь #{profile.data.profile.user_id}
                  {profile.data.profile.email ? ` · ${profile.data.profile.email}` : ' · single-user MVP'}
                </p>
              </div>
            </div>

            <div className="grid gap-2 text-sm sm:grid-cols-3 md:min-w-[30rem]">
              <div className="rounded-2xl border border-blue-100 bg-white p-3">
                <p className="text-ink/50">Темы</p>
                <strong className="text-xl">{selectedTopicsCount}</strong>
              </div>
              <div className="rounded-2xl border border-blue-100 bg-white p-3">
                <p className="text-ink/50">Любимые RSS</p>
                <strong className="text-xl">{preferredSourcesCount}</strong>
              </div>
              <div className="rounded-2xl border border-blue-100 bg-white p-3">
                <p className="text-ink/50">Скрытые RSS</p>
                <strong className="text-xl">{blockedSourcesCount}</strong>
              </div>
            </div>
          </div>

          <p className="mt-5 max-w-4xl text-sm leading-6 text-ink/65">
            Здесь настраиваются только понятные пользовательские предпочтения: интересующие темы, любимые или
            скрытые источники и уровень разнообразия выдачи. Технические сигналы поведения система учитывает сама
            и не показывает в пользовательском профиле.
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <aside className="space-y-6">
          <div className="panel rounded-[2rem] p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="label">Рекомендации</p>
                <h2 className="font-display text-3xl font-bold">Разнообразие выдачи</h2>
              </div>
              <strong className="rounded-full bg-blue-50 px-3 py-1 text-lg text-[#2563eb]">{diversity.toFixed(2)}</strong>
            </div>
            <p className="mt-3 text-sm leading-6 text-ink/60">
              Чем выше значение, тем сильнее система защищает выдачу от повторов одной темы или одного источника.
              Релевантность остаётся главным фактором, а разнообразие мягко переставляет близкие по качеству новости.
            </p>
            <input
              className="mt-5 w-full accent-[#2563eb]"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={diversity}
              onChange={(event) => setDiversity(Number(event.target.value))}
            />
            <div className="mt-3 flex justify-between text-xs text-ink/45">
              <span>Больше похожего</span>
              <span>Больше разнообразия</span>
            </div>
          </div>

          <div className="rounded-[2rem] border border-blue-100 bg-white p-6">
            <h3 className="font-display text-2xl font-bold">Как это влияет</h3>
            <p className="mt-3 text-sm leading-6 text-ink/60">
              Настройки профиля применяются в поиске, дайджестах и персональных подборках. На главной ленте они
              используются аккуратно: время публикации остаётся главным, а скрытые источники можно исключать через
              переключатель профиля.
            </p>
          </div>
        </aside>

        <div className="space-y-6">
          <div className="panel rounded-[2rem] p-6">
            <p className="label">Темы</p>
            <h2 className="font-display text-3xl font-bold">Вес интереса</h2>
            <p className="mt-2 text-sm text-ink/60">
              Ползунок выше середины мягко поднимает новости по этой теме в персональной выдаче. Низкое значение
              не блокирует тему полностью, а просто не даёт ей дополнительного бонуса.
            </p>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {topicCatalog.map((topic: TopicFilter) => {
                const value = topicWeights[topic.id] ?? 0
                return (
                  <label key={topic.id} className="rounded-2xl border border-blue-50 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold">{topic.name}</span>
                      <span className="text-sm text-ink/55">{value.toFixed(2)}</span>
                    </div>
                    <input
                      className="mt-3 w-full accent-[#2563eb]"
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={value}
                      onChange={(event) =>
                        setTopicWeights((current) => ({ ...current, [topic.id]: Number(event.target.value) }))
                      }
                    />
                  </label>
                )
              })}
            </div>
          </div>

          <div className="panel rounded-[2rem] p-6">
            <p className="label">Источники</p>
            <h2 className="font-display text-3xl font-bold">Предпочитать или исключать</h2>
            <p className="mt-2 text-sm leading-6 text-ink/60">
              В интерфейсе показаны сайты, знакомые пользователю. Если у сайта несколько RSS-лент, настройка
              применяется ко всем его техническим источникам сразу.
            </p>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {sourceCatalog.map((source) => {
                const preference = groupPreference(source.ids, sourcePrefs)
                return (
                  <div key={source.key} className="rounded-2xl border border-blue-50 bg-white p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <strong>{source.name}</strong>
                        <p className="text-xs text-ink/50">
                          {source.news_count} новостей · {source.processed_count} обработано
                        </p>
                      </div>
                      <span className="rounded-full bg-blue-50 px-2 py-1 text-xs text-[#1d4ed8]">
                        {sourcePreferenceLabel(preference)}
                      </span>
                    </div>
                    {source.sources.length > 1 && (
                      <p className="mt-2 text-xs text-ink/50">
                        {source.sources.length} RSS-ленты: {source.sources.map((item) => item.name).join(', ')}
                      </p>
                    )}
                    <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                      {(['preferred', 'neutral', 'blocked'] as SourcePreference[]).map((item) => (
                        <button
                          key={item}
                          type="button"
                          onClick={() => setSourceGroupPreference(source.ids, item)}
                          className={`rounded-full px-2 py-2 transition ${
                            preference === item ? 'bg-[#2563eb] text-white' : 'bg-blue-50 text-[#1d4ed8] hover:bg-blue-100'
                          }`}
                        >
                          {item === 'preferred' ? 'Люблю' : item === 'blocked' ? 'Скрыть' : 'Нейтр.'}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="panel flex flex-col gap-3 rounded-[2rem] p-5 shadow-soft md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="font-display text-2xl font-bold">Сохранить настройки</h3>
          <p className="text-sm text-ink/55">
            Изменения применятся к поиску, дайджестам и персональным подборкам после сохранения.
          </p>
          {save.isSuccess && <p className="mt-1 text-sm text-moss">Настройки сохранены.</p>}
          {save.error && <p className="mt-1 text-sm text-red-700">{String(save.error)}</p>}
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={save.isPending}
          className="rounded-full bg-[#2563eb] px-6 py-3 font-semibold text-white transition hover:bg-[#1d4ed8] disabled:opacity-60"
        >
          {save.isPending ? 'Сохраняю...' : 'Сохранить персонализацию'}
        </button>
      </div>
    </section>
  )
}
