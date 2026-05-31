import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router'

import { api } from '../shared/api/client'
import type { AuthTokenResponse } from '../shared/api/client'
import { useAuth } from '../shared/auth/AuthProvider'

type AuthMode = 'login' | 'register'
type AuthLocationState = { from?: string }

function authError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function AuthPage({ initialMode }: { initialMode?: AuthMode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [mode, setMode] = useState<AuthMode>(initialMode ?? (location.pathname === '/register' ? 'register' : 'login'))
  const [login, setLogin] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const auth = useAuth()
  const queryClient = useQueryClient()
  const fallbackFrom =
    location.pathname === '/login' || location.pathname === '/register'
      ? '/'
      : `${location.pathname}${location.search}`
  const from = (location.state as AuthLocationState | null)?.from ?? fallbackFrom

  useEffect(() => {
    setMode(initialMode ?? (location.pathname === '/register' ? 'register' : 'login'))
  }, [initialMode, location.pathname])

  const submitAuth = useMutation({
    mutationFn: async (): Promise<AuthTokenResponse> => {
      if (mode === 'register') {
        return api.register({
          username: username.trim(),
          email: email.trim() || null,
          password,
        })
      }
      return api.login({ login: login.trim(), password })
    },
    onSuccess: (response) => {
      auth.setSession(response)
      queryClient.clear()
      navigate(from === '/login' || from === '/register' ? '/' : from, { replace: true })
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    submitAuth.mutate()
  }

  const isRegister = mode === 'register'

  return (
    <section className="mx-auto grid min-h-[70vh] max-w-5xl gap-8 py-8 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
      <div>
        <p className="label">Аккаунт Newscope</p>
        <h1 className="font-display text-5xl font-black leading-none md:text-6xl">
          Персональная лента, поиск и дайджесты в одном профиле.
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-ink/65">
          В режиме авторизации каждый пользователь получает свои настройки, историю чатов, реакции,
          дайджесты и персонализацию. В локальном single-user режиме приложение откроется автоматически.
        </p>
      </div>

      <form onSubmit={submit} className="panel rounded-[2rem] p-6 md:p-8">
        <div className="mb-6 grid grid-cols-2 rounded-2xl bg-blue-50 p-1 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setMode('login')}
            className={`rounded-xl px-4 py-3 ${!isRegister ? 'bg-[#2563eb] text-white shadow-soft' : 'text-[#1d4ed8]'}`}
          >
            Войти
          </button>
          <button
            type="button"
            onClick={() => setMode('register')}
            className={`rounded-xl px-4 py-3 ${isRegister ? 'bg-[#2563eb] text-white shadow-soft' : 'text-[#1d4ed8]'}`}
          >
            Регистрация
          </button>
        </div>

        {isRegister ? (
          <>
            <label className="block">
              <span className="mb-2 block text-sm font-semibold text-ink/70">Имя пользователя</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                minLength={3}
                className="w-full rounded-2xl border border-blue-100 bg-white px-4 py-3 outline-none focus:border-[#2563eb]"
                placeholder="alice"
              />
            </label>
            <label className="mt-4 block">
              <span className="mb-2 block text-sm font-semibold text-ink/70">Email</span>
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                className="w-full rounded-2xl border border-blue-100 bg-white px-4 py-3 outline-none focus:border-[#2563eb]"
                placeholder="alice@example.com"
              />
            </label>
          </>
        ) : (
          <label className="block">
            <span className="mb-2 block text-sm font-semibold text-ink/70">Логин или email</span>
            <input
              value={login}
              onChange={(event) => setLogin(event.target.value)}
              required
              className="w-full rounded-2xl border border-blue-100 bg-white px-4 py-3 outline-none focus:border-[#2563eb]"
              placeholder="alice"
            />
          </label>
        )}

        <label className="mt-4 block">
          <span className="mb-2 block text-sm font-semibold text-ink/70">Пароль</span>
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            type="password"
            className="w-full rounded-2xl border border-blue-100 bg-white px-4 py-3 outline-none focus:border-[#2563eb]"
            placeholder="Минимум 8 символов"
          />
        </label>

        {submitAuth.error && <p className="mt-4 rounded-2xl bg-red-50 p-3 text-sm text-red-700">{authError(submitAuth.error)}</p>}
        {auth.error && !submitAuth.error && (
          <p className="mt-4 rounded-2xl bg-blue-50 p-3 text-sm text-ink/60">
            Для этого режима нужен вход в аккаунт.
          </p>
        )}

        <button
          type="submit"
          disabled={submitAuth.isPending}
          className="mt-6 w-full rounded-2xl bg-[#2563eb] px-5 py-4 font-semibold text-white transition hover:bg-[#1d4ed8] disabled:opacity-60"
        >
          {submitAuth.isPending ? 'Проверяю...' : isRegister ? 'Создать аккаунт' : 'Войти'}
        </button>
      </form>
    </section>
  )
}
