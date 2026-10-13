import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import AuthProvider from './auth/AuthProvider';
import ProtectedRoute from './auth/ProtectedRoute';
import Layout from './components/Layout';
import Dashboard from './Dashboard';
import ForgotPassword from './pages/ForgotPassword';
import Insights from './pages/Insights';
import Players from './pages/Players';
import RosterRisk from './pages/RosterRisk';
import CsvUpload from './pages/CsvUpload';
import Landing from './pages/Landing';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import Profile from './pages/Profile';
import Signup from './pages/Signup';
import Upload from './pages/Upload';
import VideoResults from './pages/VideoResults';

// The tracking/replay page is heavier and only used on demand: load it separately.
const TrackPlayer = lazy(() => import('./pages/TrackPlayer'));
const trackPage = (
  <Suspense fallback={<p className="px-6 py-10 text-caption text-fg-muted">Loading…</p>}>
    <TrackPlayer />
  </Suspense>
);

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Landing />} />
            <Route path="login" element={<Login />} />
            <Route path="signup" element={<Signup />} />
            <Route path="forgot-password" element={<ForgotPassword />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route element={<ProtectedRoute />}>
              <Route path="players" element={<Players />} />
              <Route path="roster" element={<RosterRisk />} />
              <Route path="roster/upload" element={<CsvUpload />} />
              <Route path="upload" element={<Upload />} />
              <Route path="profile" element={<Profile />} />
              <Route path="history" element={<Navigate to="/profile" replace />} />
              <Route path="videos/:id" element={<VideoResults />} />
              <Route path="videos/:id/track" element={trackPage} />
              <Route path="videos/:id/track/:trackId" element={trackPage} />
              <Route path="insights" element={<Insights />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
