import { FormEvent, useState } from 'react'

export function SearchBox({ onSearch, isLoading }: { onSearch: (query: string) => void; isLoading?: boolean }) {
  const [query, setQuery] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    if (query.trim()) onSearch(query.trim())
  }

  return (
    <form onSubmit={submit} className="panel flex flex-col gap-3 rounded-[2rem] p-3 md:flex-row">
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Найти новости, событие, компанию или тему..."
        className="min-h-14 flex-1 rounded-[1.4rem] border border-blue-100 bg-white px-5 text-lg outline-none transition focus:border-[#2563eb]"
      />
      <button
        disabled={isLoading}
        className="rounded-[1.4rem] bg-[#2563eb] px-7 py-4 font-semibold text-white transition hover:bg-[#1d4ed8] disabled:opacity-50"
      >
        {isLoading ? 'Ищу...' : 'Искать'}
      </button>
    </form>
  )
}
