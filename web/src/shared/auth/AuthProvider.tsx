import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api, clearStoredAccessToken, getStoredAccessToken, setStoredAccessToken } from '../api/client'
import type { AuthTokenResponse, AuthUser } from '../api/client'

type AuthContextValue = {
  user: AuthUser | null
  isLoading: boolean
  error: string | null
  isTokenSession: boolean
  setSession: (response: AuthTokenResponse) => void
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isTokenSession, setIsTokenSession] = useState(Boolean(getStoredAccessToken()))

  const refreshUser = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const current = await api.me()
      setUser(current)
      setIsTokenSession(Boolean(getStoredAccessToken()))
    } catch (err) {
      clearStoredAccessToken()
      setUser(null)
      setIsTokenSession(false)
      setError(errorMessage(err))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void refreshUser()
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      error,
      isTokenSession,
      setSession: (response: AuthTokenResponse) => {
        setStoredAccessToken(response.access_token)
        setUser(response.user)
        setIsTokenSession(true)
        setError(null)
      },
      logout: () => {
        if (getStoredAccessToken()) {
          void api.logout().catch(() => undefined)
        }
        clearStoredAccessToken()
        setUser(null)
        setIsTokenSession(false)
      },
      refreshUser,
    }),
    [error, isLoading, isTokenSession, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return value
}
