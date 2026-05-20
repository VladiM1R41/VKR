import { Link } from 'react-router'
import type { NewsSummary } from '../../shared/api/client'

export function NewsCard({ item }: { item: NewsSummary }) {
  return (
    <Link
      to={`/news/${item.id}`}
      className="group block rounded-[1.35rem] border border-blue-100 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-[#2563eb]/35 hover:shadow-panel"
    >
      <article>
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-ink/55">
            <span className="rounded-full bg-blue-50 px-3 py-1 font-semibold text-[#2563eb]">{item.source.name}</span>
            <span>grade {item.content_grade}</span>
            <span>{item.urgency}</span>
            {item.published_at && <span>{new Date(item.published_at).toLocaleString('ru-RU')}</span>}
          </div>
          <h3 className="font-display text-2xl font-bold leading-tight group-hover:text-[#2563eb]">{item.title}</h3>
          {item.snippet && <p className="mt-2 line-clamp-2 text-ink/70">{item.snippet}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {item.topics.slice(0, 4).map((topic) => (
              <span key={topic.id} className="rounded-full bg-blue-50 px-3 py-1 text-xs text-ink/65">
                {topic.name}
              </span>
            ))}
          </div>
        </div>
      </article>
    </Link>
  )
}
