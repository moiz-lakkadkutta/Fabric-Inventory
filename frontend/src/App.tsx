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
import AccountingHub from '@/pages/accounting/AccountingHub';
import InventoryList from '@/pages/inventory/InventoryList';
import LotDetail from '@/pages/inventory/LotDetail';
import JobWorkOverview from '@/pages/jobwork/JobWorkOverview';
import ManufacturingPipeline from '@/pages/manufacturing/ManufacturingPipeline';
import PartyDetail from '@/pages/masters/PartyDetail';
import PartyList from '@/pages/masters/PartyList';
import PurchaseOrderList from '@/pages/purchase/PurchaseOrderList';
import ReportsHub from '@/pages/reports/ReportsHub';
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
      { path: 'purchase', element: <PurchaseOrderList /> },
      { path: 'inventory', element: <InventoryList /> },
      { path: 'inventory/lots/:id', element: <LotDetail /> },
      { path: 'manufacturing', element: <ManufacturingPipeline /> },
      { path: 'jobwork', element: <JobWorkOverview /> },
      { path: 'accounting', element: <AccountingHub /> },
      { path: 'reports', element: <ReportsHub /> },
      { path: 'masters', element: <Navigate to="/masters/parties" replace /> },
      { path: 'masters/parties', element: <PartyList /> },
      { path: 'masters/parties/:id', element: <PartyDetail /> },
      { path: 'admin', element: <Placeholder title="Admin" task="TASK-019" /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
