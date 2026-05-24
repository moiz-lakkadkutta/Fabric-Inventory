import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';

import { RequireAuth } from '@/components/auth/RequireAuth';
import { AppLayout } from '@/components/layout/AppLayout';
import { useAuthBootstrap } from '@/hooks/useAuth';
import AcceptInvite from '@/pages/auth/AcceptInvite';
import Forgot from '@/pages/auth/Forgot';
import Invite from '@/pages/auth/Invite';
import Login from '@/pages/auth/Login';
import Mfa from '@/pages/auth/Mfa';
import Onboarding from '@/pages/auth/Onboarding';
import ResetPassword from '@/pages/auth/ResetPassword';
import Dashboard from '@/pages/Dashboard';
import NotFound from '@/pages/NotFound';
import Placeholder from '@/pages/Placeholder';
import AccountingHub from '@/pages/accounting/AccountingHub';
import BankReconcile from '@/pages/accounting/BankReconcile';
import AdminHub from '@/pages/admin/AdminHub';
import Migrations from '@/pages/admin/Migrations';
import InventoryList from '@/pages/inventory/InventoryList';
import LotDetail from '@/pages/inventory/LotDetail';
import JobWorkOverview from '@/pages/jobwork/JobWorkOverview';
import BomCreateWizard from '@/pages/manufacturing/BomCreateWizard';
import BomsList from '@/pages/manufacturing/BomsList';
import CostCentresList from '@/pages/manufacturing/CostCentresList';
import DesignsList from '@/pages/manufacturing/DesignsList';
import ManufacturingPipeline from '@/pages/manufacturing/ManufacturingPipeline';
import MoCreateWizard from '@/pages/manufacturing/MoCreateWizard';
import MoDetail from '@/pages/manufacturing/MoDetail';
import MoList from '@/pages/manufacturing/MoList';
import OperationsList from '@/pages/manufacturing/OperationsList';
import RoutingCreateWizard from '@/pages/manufacturing/RoutingCreateWizard';
import RoutingsList from '@/pages/manufacturing/RoutingsList';
import ItemDetail from '@/pages/masters/ItemDetail';
import ItemList from '@/pages/masters/ItemList';
import PartyDetail from '@/pages/masters/PartyDetail';
import PartyList from '@/pages/masters/PartyList';
import GrnCreate from '@/pages/purchase/GrnCreate';
import GrnDetail from '@/pages/purchase/GrnDetail';
import GrnList from '@/pages/purchase/GrnList';
import PurchaseInvoiceCreate from '@/pages/purchase/PurchaseInvoiceCreate';
import PurchaseInvoiceDetail from '@/pages/purchase/PurchaseInvoiceDetail';
import PurchaseInvoiceList from '@/pages/purchase/PurchaseInvoiceList';
import PurchaseOrderCreate from '@/pages/purchase/PurchaseOrderCreate';
import PurchaseOrderDetail from '@/pages/purchase/PurchaseOrderDetail';
import PurchaseOrderList from '@/pages/purchase/PurchaseOrderList';
import ReportsHub from '@/pages/reports/ReportsHub';
import DeliveryChallanCreate from '@/pages/sales/DeliveryChallanCreate';
import DeliveryChallanDetail from '@/pages/sales/DeliveryChallanDetail';
import DeliveryChallanList from '@/pages/sales/DeliveryChallanList';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';
import InvoiceDetail from '@/pages/sales/InvoiceDetail';
import InvoiceList from '@/pages/sales/InvoiceList';
import SalesOrderCreate from '@/pages/sales/SalesOrderCreate';
import SalesOrderDetail from '@/pages/sales/SalesOrderDetail';
import SalesOrderList from '@/pages/sales/SalesOrderList';

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/mfa', element: <Mfa /> },
  { path: '/forgot', element: <Forgot /> },
  // CUT-303: /reset/:token is a public route (outside RequireAuth) —
  // the whole point is letting the user back in when they can't log
  // in. The orgname carried as `?org=` is read by the page itself.
  { path: '/reset/:token', element: <ResetPassword /> },
  { path: '/invite', element: <Invite /> },
  // CUT-304: real invite-accept page lives at /invite/:token (token is
  // the raw secret from the BE-minted invite link). Public route —
  // outside RequireAuth — the invitee has no session yet.
  { path: '/invite/:token', element: <AcceptInvite /> },
  { path: '/onboarding', element: <Onboarding /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'sales', element: <Navigate to="/sales/invoices" replace /> },
      { path: 'sales/invoices', element: <InvoiceList /> },
      { path: 'sales/invoices/new', element: <InvoiceCreate /> },
      { path: 'sales/invoices/:id', element: <InvoiceDetail /> },
      { path: 'sales/quotes', element: <Placeholder title="Quotes" task="TASK-038" /> },
      { path: 'sales/orders', element: <SalesOrderList /> },
      { path: 'sales/orders/new', element: <SalesOrderCreate /> },
      { path: 'sales/orders/:id', element: <SalesOrderDetail /> },
      // Wave-2 sidebar uses /sales/challans; CUT-203 settles on
      // /sales/delivery-challans (matches the BE route + cutover plan
      // wording). Old path redirects so any stale tab keeps working.
      { path: 'sales/challans', element: <Navigate to="/sales/delivery-challans" replace /> },
      { path: 'sales/delivery-challans', element: <DeliveryChallanList /> },
      { path: 'sales/delivery-challans/new', element: <DeliveryChallanCreate /> },
      { path: 'sales/delivery-challans/:id', element: <DeliveryChallanDetail /> },
      { path: 'sales/returns', element: <Placeholder title="Returns" task="TASK-038" /> },
      {
        path: 'sales/credit-control',
        element: <Placeholder title="Credit control" task="TASK-055" />,
      },
      { path: 'purchase', element: <PurchaseOrderList /> },
      { path: 'purchase/new', element: <PurchaseOrderCreate /> },
      { path: 'purchase/grns', element: <GrnList /> },
      { path: 'purchase/grns/new', element: <GrnCreate /> },
      { path: 'purchase/grns/:id', element: <GrnDetail /> },
      { path: 'purchase/invoices', element: <PurchaseInvoiceList /> },
      { path: 'purchase/invoices/new', element: <PurchaseInvoiceCreate /> },
      { path: 'purchase/invoices/:id', element: <PurchaseInvoiceDetail /> },
      // PO detail uses :id last so the more-specific /grns and /invoices
      // routes match first (React Router v7 matches in declaration order
      // for non-nested patterns of the same depth).
      { path: 'purchase/:id', element: <PurchaseOrderDetail /> },
      { path: 'inventory', element: <InventoryList /> },
      { path: 'inventory/lots/:id', element: <LotDetail /> },
      { path: 'manufacturing', element: <ManufacturingPipeline /> },
      // TASK-TR-A14-FU: MO list + detail live above the legacy pipeline
      // kanban. The /new stub is a reachable placeholder until the
      // creation form ships as its own task.
      { path: 'manufacturing/mo', element: <MoList /> },
      { path: 'manufacturing/mo/new', element: <MoCreateWizard /> },
      { path: 'manufacturing/mo/:id', element: <MoDetail /> },
      // TASK-TR-E1: Designs master list. Sits under /manufacturing for
      // navigation locality (the MO wizard reads from this list).
      { path: 'manufacturing/designs', element: <DesignsList /> },
      // TASK-TR-E1-COSTCENTRES: master-data list for cost centres
      // (lives under Manufacturing because the only consumers are
      // operation masters / MO rollups).
      { path: 'manufacturing/cost-centres', element: <CostCentresList /> },
      // TASK-TR-E1-OPERATIONS: operation-master registry feeding the
      // routing graph in the MO wizard.
      { path: 'manufacturing/operations', element: <OperationsList /> },
      // TASK-TR-E1-BOMS: BOM list grouped by design + 3-tab create wizard.
      { path: 'manufacturing/boms', element: <BomsList /> },
      { path: 'manufacturing/boms/new', element: <BomCreateWizard /> },
      // TASK-TR-E1-ROUTINGS: routing master list + 3-tab create wizard
      // (DAG editor in the operations tab).
      { path: 'manufacturing/routings', element: <RoutingsList /> },
      { path: 'manufacturing/routings/new', element: <RoutingCreateWizard /> },
      { path: 'jobwork', element: <JobWorkOverview /> },
      { path: 'accounting', element: <AccountingHub /> },
      // TR-B3: full-page bank-statement reconciliation flow. Lives
      // under /accounting so the breadcrumb / role-gate inherits the
      // AccountingHub posture.
      { path: 'accounting/bank-recon', element: <BankReconcile /> },
      { path: 'reports', element: <ReportsHub /> },
      { path: 'masters', element: <Navigate to="/masters/parties" replace /> },
      { path: 'masters/parties', element: <PartyList /> },
      { path: 'masters/parties/:id', element: <PartyDetail /> },
      { path: 'masters/items', element: <ItemList /> },
      { path: 'masters/items/:id', element: <ItemDetail /> },
      { path: 'admin', element: <AdminHub /> },
      { path: 'admin/migrations', element: <Migrations /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  useAuthBootstrap();
  return <RouterProvider router={router} />;
}
