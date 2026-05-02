import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';

import { AppLayout } from '@/components/layout/AppLayout';
import Forgot from '@/pages/auth/Forgot';
import Invite from '@/pages/auth/Invite';
import Login from '@/pages/auth/Login';
import Mfa from '@/pages/auth/Mfa';
import Onboarding from '@/pages/auth/Onboarding';
import Dashboard from '@/pages/Dashboard';
import NotFound from '@/pages/NotFound';
import Placeholder from '@/pages/Placeholder';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';
import InvoiceDetail from '@/pages/sales/InvoiceDetail';
import InvoiceList from '@/pages/sales/InvoiceList';

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/mfa', element: <Mfa /> },
  { path: '/forgot', element: <Forgot /> },
  { path: '/invite', element: <Invite /> },
  { path: '/onboarding', element: <Onboarding /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'sales', element: <Navigate to="/sales/invoices" replace /> },
      { path: 'sales/invoices', element: <InvoiceList /> },
      { path: 'sales/invoices/new', element: <InvoiceCreate /> },
      { path: 'sales/invoices/:id', element: <InvoiceDetail /> },
      { path: 'sales/quotes', element: <Placeholder title="Quotes" task="TASK-038" /> },
      { path: 'sales/orders', element: <Placeholder title="Sales orders" task="TASK-038" /> },
      {
        path: 'sales/challans',
        element: <Placeholder title="Delivery challans" task="TASK-033" />,
      },
      { path: 'sales/returns', element: <Placeholder title="Returns" task="TASK-038" /> },
      {
        path: 'sales/credit-control',
        element: <Placeholder title="Credit control" task="TASK-055" />,
      },
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
