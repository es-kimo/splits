import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ClubGate, MemberGate } from './components/ClubGate'
import { ToastProvider } from './components/Toast'
import { AdminPage } from './pages/AdminPage'
import { BoardPage } from './pages/BoardPage'
import { JoinPage } from './pages/JoinPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/g/:token" element={<JoinPage />} />
            <Route
              path="/admin"
              element={
                // 모임원이 한 명도 없을 때도 총무는 들어올 수 있어야 하므로 이름 고르기를 거치지 않는다.
                <ClubGate>
                  <AdminPage />
                </ClubGate>
              }
            />
            <Route
              path="/"
              element={
                <ClubGate>
                  <MemberGate>
                    <BoardPage />
                  </MemberGate>
                </ClubGate>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
