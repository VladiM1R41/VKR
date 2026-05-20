import { NavLink, Outlet } from 'react-router'

const links = [
  ['/', 'Лента'],
  ['/chat', 'Чаты'],
  ['/profile', 'Профиль'],
  ['/digest', 'Дайджесты'],
  ['/admin', 'Админ панель'],
] as const

export function RootLayout() {
  return (
    <div className="min-h-screen bg-white text-ink">
      <header className="sticky top-0 z-20 border-b border-blue-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-5 py-4 xl:px-8">
          <NavLink to="/" className="font-display text-2xl font-bold tracking-tight">
            Newscope
          </NavLink>
          <nav className="flex flex-wrap gap-2">
            {links.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `rounded-full px-4 py-2 text-sm transition ${
                    isActive ? 'bg-[#2563eb] text-white' : 'text-ink/70 hover:bg-blue-50 hover:text-[#1d4ed8]'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-5 py-8 xl:px-8">
        <Outlet />
      </main>
    </div>
  )
}
