import { Outlet } from 'react-router-dom';

import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppLayout() {
  return (
    <div className="flex h-full flex-col" style={{ background: 'var(--bg-canvas)' }}>
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-[1280px] px-4 py-6 md:px-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
