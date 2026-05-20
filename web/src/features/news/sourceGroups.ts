import type { SourceFilter } from '../../shared/api/client'

export type SourceGroup = {
  key: string
  name: string
  ids: number[]
  news_count: number
  processed_count: number
  sources: SourceFilter[]
}

const SUFFIX_PATTERN = /\s+(news|articles|corp|main)$/i

export function sourceDisplayName(name: string): string {
  return name.replace(SUFFIX_PATTERN, '').trim()
}

export function groupSources(sources: SourceFilter[] = []): SourceGroup[] {
  const byKey = new Map<string, SourceGroup>()

  for (const source of sources) {
    const displayName = sourceDisplayName(source.name)
    const key = displayName.toLocaleLowerCase('ru-RU')
    const group = byKey.get(key)
    if (group) {
      group.ids.push(source.id)
      group.news_count += source.news_count
      group.processed_count += source.processed_count
      group.sources.push(source)
    } else {
      byKey.set(key, {
        key,
        name: displayName,
        ids: [source.id],
        news_count: source.news_count,
        processed_count: source.processed_count,
        sources: [source],
      })
    }
  }

  return [...byKey.values()].sort((left, right) => left.name.localeCompare(right.name, 'ru'))
}
