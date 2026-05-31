import { Navigate, NavLink, Outlet, useLocation } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'

import { AuthPage } from '../pages/AuthPage'
import { useAuth } from '../shared/auth/AuthProvider'
import { LoadingBlock } from '../shared/ui/State'

const links = [
  ['/', 'Лента'],
  ['/chat', 'Чаты'],
  ['/profile', 'Профиль'],
  ['/digest', 'Дайджесты'],
  ['/admin', 'Админ панель', true],
] as const

export function RootLayout() {
  const auth = useAuth()
  const location = useLocation()
  const queryClient = useQueryClient()
  const isAuthPath = location.pathname === '/login' || location.pathname === '/register'
  const isAdminPath = location.pathname.startsWith('/admin')

  function logout() {
    auth.logout()
    queryClient.clear()
  }

  return (
    <div className="min-h-screen bg-white text-ink">
      <header className="sticky top-0 z-20 border-b border-blue-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-5 py-4 xl:px-8">
          <NavLink to="/" className="font-display text-2xl font-bold tracking-tight">
            Newscope
          </NavLink>
          {auth.user && (
            <nav className="flex flex-wrap items-center justify-end gap-2">
              {links
                .filter(([, , adminOnly]) => !adminOnly || auth.user?.is_admin)
                .map(([to, label]) => (
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
              <span className="rounded-full bg-blue-50 px-3 py-2 text-sm text-[#1d4ed8]">
                {auth.user.username}
              </span>
              {auth.isTokenSession && (
                <button
                  type="button"
                  onClick={logout}
                  className="rounded-full border border-blue-100 px-3 py-2 text-sm text-ink/65 hover:bg-blue-50"
                >
                  Выйти
                </button>
              )}
            </nav>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-5 py-8 xl:px-8">
        {auth.isLoading ? (
          <LoadingBlock label="Проверяю сессию..." />
        ) : auth.user ? (
          isAuthPath ? <Navigate to="/" replace /> : isAdminPath && !auth.user.is_admin ? <Navigate to="/" replace /> : <Outlet />
        ) : !isAuthPath ? (
          <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
        ) : (
          <AuthPage initialMode={location.pathname === '/register' ? 'register' : 'login'} />
        )}
      </main>
    </div>
  )
}
