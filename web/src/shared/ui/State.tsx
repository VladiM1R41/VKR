export function LoadingBlock({ label = 'Загрузка...' }: { label?: string }) {
  return <div className="rounded-3xl border border-dashed border-blue-200 bg-blue-50/40 p-8 text-ink/60">{label}</div>
}

export function ErrorBlock({ error }: { error: unknown }) {
  return (
    <div className="rounded-3xl border border-red-900/20 bg-red-50 p-5 text-sm text-red-900">
      {error instanceof Error ? error.message : 'Не удалось выполнить запрос'}
    </div>
  )
}
