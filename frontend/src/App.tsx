import { createBrowserRouter, RouterProvider } from 'react-router-dom';

import { AppLayout } from '@/components/layout/AppLayout';
import Dashboard from '@/pages/Dashboard';
import NotFound from '@/pages/NotFound';
import Placeholder from '@/pages/Placeholder';

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'sales', element: <Placeholder title="Sales" task="TASK-038" /> },
      { path: 'purchase', element: <Placeholder title="Purchase" task="TASK-031" /> },
      { path: 'inventory', element: <Placeholder title="Inventory" task="TASK-024" /> },
      { path: 'accounting', element: <Placeholder title="Accounting" task="TASK-044" /> },
      { path: 'masters', element: <Placeholder title="Masters" task="TASK-020" /> },
      { path: 'admin', element: <Placeholder title="Admin" task="TASK-019" /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
