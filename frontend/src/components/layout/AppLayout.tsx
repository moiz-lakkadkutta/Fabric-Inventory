import { Outlet } from 'react-router-dom';

import { CommandPaletteProvider, useCommandPalette } from '@/hooks/useCommandPalette';

import { BottomNav } from './BottomNav';
import { CommandPalette } from './CommandPalette';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppLayout() {
  return (
    <CommandPaletteProvider>
      <AppLayoutInner />
    </CommandPaletteProvider>
  );
}

function AppLayoutInner() {
  const { open, setOpen } = useCommandPalette();
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
      <BottomNav />
      <CommandPalette open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
