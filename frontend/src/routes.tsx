import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, type RouteObject } from 'react-router';
import { Spin } from 'antd';

import PanelLayout from '@/layouts/PanelLayout';

const IndexPage = lazy(() => import('@/pages/index/IndexPage'));
const InboundsPage = lazy(() => import('@/pages/inbounds/InboundsPage'));
const ClientsPage = lazy(() => import('@/pages/clients/ClientsPage'));
const GroupsPage = lazy(() => import('@/pages/groups/GroupsPage'));
const NodesPage = lazy(() => import('@/pages/nodes/NodesPage'));
const HostsPage = lazy(() => import('@/pages/hosts/HostsPage'));
const SettingsPage = lazy(() => import('@/pages/settings/SettingsPage'));
const XrayPage = lazy(() => import('@/pages/xray/XrayPage'));
const ApiDocsPage = lazy(() => import('@/pages/api-docs/ApiDocsPage'));
const AdminsPage = lazy(() => import('@/pages/admins/AdminsPage'));
const ResellerDashboardPage = lazy(() => import('@/pages/reseller/ResellerDashboardPage'));

function withSuspense(node: React.ReactNode) {
  return (
    <Suspense
      fallback={
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            minHeight: '60vh',
          }}
        >
          <Spin size="large" />
        </div>
      }
    >
      {node}
    </Suspense>
  );
}

function IndexRoute() {
  const role = (typeof window !== 'undefined' && window.X_UI_ROLE) || 'super_admin';
  const permissions = new Set(
    typeof window !== 'undefined' && Array.isArray(window.X_UI_PERMS) ? window.X_UI_PERMS : [],
  );
  if (permissions.has('inbounds.scoped')) return <Navigate to="/usage" replace />;
  // The system dashboard calls server-wide status, update, and settings APIs.
  // Roles that do not have those permissions should land on an allowed page
  // instead of rendering a dashboard full of expected 403 responses.
  if (role !== 'super_admin' && !permissions.has('settings.manage') && !permissions.has('xray.manage')) {
    return <Navigate to={permissions.has('inbounds.view') ? '/inbounds' : '/clients'} replace />;
  }
  return withSuspense(<IndexPage />);
}

function AdminsRoute() {
  const role = (typeof window !== 'undefined' && window.X_UI_ROLE) || 'super_admin';
  if (role !== 'super_admin') return <Navigate to="/" replace />;
  return withSuspense(<AdminsPage />);
}

function ResellerRoute() {
  const scoped = typeof window !== 'undefined' && Array.isArray(window.X_UI_PERMS) && window.X_UI_PERMS.includes('inbounds.scoped');
  if (!scoped) return <Navigate to="/" replace />;
  return withSuspense(<ResellerDashboardPage />);
}

const routes: RouteObject[] = [
  {
    path: '/',
    element: <PanelLayout />,
    children: [
      { index: true, element: <IndexRoute /> },
      { path: 'inbounds', element: withSuspense(<InboundsPage />) },
      { path: 'clients', element: withSuspense(<ClientsPage />) },
      { path: 'groups', element: withSuspense(<GroupsPage />) },
      { path: 'nodes', element: withSuspense(<NodesPage />) },
      { path: 'hosts', element: withSuspense(<HostsPage />) },
      { path: 'settings', element: withSuspense(<SettingsPage />) },
      { path: 'xray', element: withSuspense(<XrayPage />) },
      { path: 'outbound', element: withSuspense(<XrayPage />) },
      { path: 'routing', element: withSuspense(<XrayPage />) },
      { path: 'api-docs', element: withSuspense(<ApiDocsPage />) },
      { path: 'admins', element: <AdminsRoute /> },
      { path: 'usage', element: <ResellerRoute /> },
    ],
  },
];

function computeBasename() {
  const raw = (typeof window !== 'undefined' && window.X_UI_BASE_PATH) || '/';
  const trimmed = raw.replace(/\/+$/, '');
  return `${trimmed}/panel`;
}

export const router = createBrowserRouter(routes, {
  basename: computeBasename(),
});
