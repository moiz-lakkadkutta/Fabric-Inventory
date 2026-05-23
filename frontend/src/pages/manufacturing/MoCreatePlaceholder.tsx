/*
 * MoCreatePlaceholder — TASK-TR-A14-FU.
 *
 * The actual MO creation form (BOM picker, routing picker, qty, dates)
 * lives in its own UI task (SCR-MFG-004). The list page's "+ New MO"
 * CTA still needs a reachable destination so users don't hit a 404;
 * this placeholder keeps the nav graph closed.
 */

import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';

export default function MoCreatePlaceholder() {
  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/manufacturing/mo"
          aria-label="Back to MOs"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>New MO</h1>
      </header>

      <div
        className="space-y-3 p-6"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>MO creation form ships next</h2>
        <p
          style={{
            fontSize: 13.5,
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
            margin: 0,
          }}
        >
          The full create-MO flow (design + BOM + routing picker, qty + planned dates) is tracked
          under a separate UI task. Until it lands, MOs come in via the API directly or the seed
          harness.
        </p>
        <div>
          <Link to="/manufacturing/mo">
            <Button variant="outline">Back to MO list</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
