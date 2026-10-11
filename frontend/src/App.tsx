import { lazy, Suspense } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import Layout from './components/Layout';
import { Skeleton } from './components/ui';
import { useAuth } from './lib/auth';
import Login from './pages/Login';

const Analytics = lazy(() => import('./pages/Analytics'));
const Insights = lazy(() => import('./pages/Insights'));
const Chat = lazy(() => import('./pages/Chat'));
const Invite = lazy(() => import('./pages/Invite'));
const ChatAnalysis = lazy(() => import('./pages/ChatAnalysis'));
const ClientPending = lazy(() => import('./pages/ClientPending'));
const Executive = lazy(() => import('./pages/Executive'));
const ProjectDashboard = lazy(() => import('./pages/ProjectDashboard'));
const Projects = lazy(() => import('./pages/Projects'));
const Reports = lazy(() => import('./pages/Reports'));
const Risks = lazy(() => import('./pages/Risks'));
const Sales = lazy(() => import('./pages/Sales'));
const Settings = lazy(() => import('./pages/Settings'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Team = lazy(() => import('./pages/Team'));
const Timeline = lazy(() => import('./pages/Timeline'));

function Protected() {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="p-8"><Skeleton className="h-8 w-60" /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <Outlet />;
}

const Fallback = () => <div className="space-y-3 p-2"><Skeleton className="h-8 w-60" /><Skeleton className="h-40" /></div>;

/** Client viewers have no company dashboard; send them to their projects instead. */
function Home() {
  const { can } = useAuth();
  return can('analytics:view') ? <Executive /> : <Navigate to="/projects" replace />;
}

export default function App() {
  return (
    <Suspense fallback={<Fallback />}>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite/:token" element={<Invite />} />
      <Route element={<Protected />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="projects" element={<Projects />} />
          <Route path="chat" element={<Chat />} />
          <Route path="chat/:roomId" element={<Chat />} />
          <Route path="settings" element={<Settings />} />
          <Route path="p/:projectId">
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<ProjectDashboard />} />
            <Route path="chat" element={<ChatAnalysis />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="team" element={<Team />} />
            <Route path="client-pending" element={<ClientPending />} />
            <Route path="sales" element={<Sales />} />
            <Route path="risks" element={<Risks />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="reports" element={<Reports />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="insights" element={<Insights />} />
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
    </Suspense>
  );
}
