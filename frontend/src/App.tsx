import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Admin } from './pages/Admin'
import { History } from './pages/History'
import { Home } from './pages/Home'
import { Predictions } from './pages/Predictions'
import { Quiniela } from './pages/Quiniela'
import { ConfirmEmail, ResetPassword } from './pages/QuinielaLinks'
import { Standings } from './pages/Standings'
import { Loading } from './components/ui'

// Las páginas con gráficas se cargan bajo demanda (Recharts pesa).
const Performance = lazy(() => import('./pages/Performance').then((m) => ({ default: m.Performance })))
const Teams = lazy(() => import('./pages/Teams').then((m) => ({ default: m.Teams })))
const TeamDetail = lazy(() => import('./pages/Teams').then((m) => ({ default: m.TeamDetail })))

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="tabla" element={<Standings />} />
        <Route path="quiniela" element={<Quiniela />} />
        <Route path="quiniela/confirmar" element={<ConfirmEmail />} />
        <Route path="quiniela/restablecer" element={<ResetPassword />} />
        <Route path="predicciones" element={<Predictions />} />
        <Route path="historico" element={<History />} />
        <Route path="equipos" element={<Suspense fallback={<Loading />}><Teams /></Suspense>} />
        <Route path="equipos/:id" element={<Suspense fallback={<Loading />}><TeamDetail /></Suspense>} />
        <Route path="rendimiento" element={<Suspense fallback={<Loading />}><Performance /></Suspense>} />
        <Route path="admin" element={<Admin />} />
        <Route path="*" element={<p className="text-sm text-slate-500">Página no encontrada.</p>} />
      </Route>
    </Routes>
  )
}
