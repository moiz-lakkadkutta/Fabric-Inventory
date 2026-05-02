import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';

import { AppLayout } from '@/components/layout/AppLayout';
import Forgot from '@/pages/auth/Forgot';
import Login from '@/pages/auth/Login';
import Mfa from '@/pages/auth/Mfa';
import Dashboard from '@/pages/Dashboard';
import NotFound from '@/pages/NotFound';
import Placeholder from '@/pages/Placeholder';
import InvoiceList from '@/pages/sales/InvoiceList';

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/mfa', element: <Mfa /> },
  { path: '/forgot', element: <Forgot /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'sales', element: <Navigate to="/sales/invoices" replace /> },
      { path: 'sales/invoices', element: <InvoiceList /> },
      { path: 'purchase', element: <Placeholder title="Purchase" task="TASK-031" /> },
      { path: 'inventory', element: <Placeholder title="Inventory" task="TASK-024" /> },
      { path: 'manufacturing', element: <Placeholder title="Manufacturing" task="Phase 3" /> },
      { path: 'jobwork', element: <Placeholder title="Job work" task="Phase 3" /> },
      { path: 'accounting', element: <Placeholder title="Accounts" task="TASK-044" /> },
      { path: 'reports', element: <Placeholder title="Reports" task="TASK-046" /> },
      { path: 'masters', element: <Placeholder title="Masters" task="TASK-020" /> },
      { path: 'admin', element: <Placeholder title="Admin" task="TASK-019" /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
