import { Outlet } from 'react-router-dom';

import { Sidebar } from './Sidebar';

export function AppLayout() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
