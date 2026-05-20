import { createBrowserRouter } from 'react-router'

import { RootLayout } from './RootLayout'
import { AdminPage } from '../pages/AdminPage'
import { ChatPage } from '../pages/ChatPage'
import { DigestPage } from '../pages/DigestPage'
import { HomePage } from '../pages/HomePage'
import { NewsDetailPage } from '../pages/NewsDetailPage'
import { ProfilePage } from '../pages/ProfilePage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <RootLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'news/:newsId', element: <NewsDetailPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'chat/:sessionId', element: <ChatPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'digest', element: <DigestPage /> },
      { path: 'admin', element: <AdminPage /> },
    ],
  },
])

