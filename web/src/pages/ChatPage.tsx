import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { api } from '../shared/api/client'
import type { ChatResponse } from '../shared/api/client'
import { queryKeys } from '../shared/api/queryKeys'
import { ErrorBlock } from '../shared/ui/State'

function displaySessionTitle(title: string | undefined, id: number): string {
  const normalized = (title ?? '').trim()
  if (!normalized || normalized.includes('???') || normalized.includes('����')) return `Сессия #${id}`
  return normalized
}

export function ChatPage() {
  const { sessionId } = useParams()
  const [message, setMessage] = useState('')
  const [lastResponse, setLastResponse] = useState<ChatResponse | null>(null)
  const queryClient = useQueryClient()
  const sessions = useQuery({ queryKey: queryKeys.chatSessions, queryFn: api.chatSessions })
  const messages = useQuery({
    queryKey: queryKeys.chatMessages(sessionId || 'new'),
    queryFn: () => api.chatMessages(sessionId!),
    enabled: Boolean(sessionId),
  })
  const chat = useMutation({
    mutationFn: () => api.chat(message, sessionId ? Number(sessionId) : undefined),
    onSuccess: (data) => {
      setLastResponse(data)
      setMessage('')
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions })
      if (data.session_id) queryClient.invalidateQueries({ queryKey: queryKeys.chatMessages(data.session_id) })
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (message.trim()) chat.mutate()
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <aside className="panel rounded-[2rem] p-5">
        <h2 className="font-display text-2xl font-bold">Чаты</h2>
        <div className="mt-4 space-y-2">
          {sessions.data?.items.map((item) => (
            <Link key={item.id} to={`/chat/${item.id}`} className="block rounded-2xl px-3 py-2 hover:bg-blue-50 hover:text-[#1d4ed8]">
              {displaySessionTitle(item.title, item.id)}
              <span className="block text-xs text-ink/45">{item.message_count} сообщений</span>
            </Link>
          ))}
        </div>
      </aside>
      <section className="panel min-h-[70vh] rounded-[2rem] p-6">
        <h1 className="font-display text-4xl font-bold">Вопрос по новостям</h1>
        {messages.data?.messages.map((item, index) => (
          <div key={index} className={`mt-4 rounded-3xl p-4 ${item.role === 'user' ? 'bg-blue-50' : 'bg-white'}`}>
            <div className="label mb-1">{item.role === 'user' ? 'пользователь' : 'ассистент'}</div>
            <p className="whitespace-pre-wrap">{item.content}</p>
          </div>
        ))}
        {lastResponse && (
          <div className="mt-5 rounded-3xl border border-blue-100 bg-white p-5">
            <div className="label mb-2">Последний ответ</div>
            <p className="whitespace-pre-wrap leading-7">{lastResponse.answer}</p>
            {!!lastResponse.sources.length && (
              <div className="mt-5">
                <div className="label mb-2">Источники ответа</div>
                <div className="flex flex-wrap gap-2">
                  {lastResponse.sources.slice(0, 8).map((source, index) => {
                    const label = `${index + 1}. ${source.source_name}: ${source.title}`
                    const className =
                      'max-w-[320px] truncate rounded-full border border-blue-100 bg-blue-50 px-3 py-2 text-sm font-semibold text-[#1d4ed8] hover:border-[#2563eb] hover:bg-white'
                    return source.url ? (
                      <a
                        key={`${source.news_id}-${index}`}
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        title={label}
                        className={className}
                      >
                        {label}
                      </a>
                    ) : (
                      <Link
                        key={`${source.news_id}-${index}`}
                        to={`/news/${source.news_id}`}
                        title={label}
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
        )}
        {chat.error && (
          <div className="mt-4">
            <ErrorBlock error={chat.error} />
          </div>
        )}
        <form onSubmit={submit} className="mt-6 flex flex-col gap-3 md:flex-row">
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            className="min-h-24 flex-1 rounded-3xl border border-blue-100 bg-white p-4 outline-none focus:border-[#2563eb]"
            placeholder="Что произошло? Почему это важно?"
          />
          <button className="rounded-3xl bg-[#2563eb] px-8 py-4 font-semibold text-white hover:bg-[#1d4ed8]" disabled={chat.isPending}>
            {chat.isPending ? 'Генерирую...' : 'Спросить'}
          </button>
        </form>
      </section>
    </div>
  )
}
