import { Link } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';

export default function Mfa() {
  return (
    <AuthShell>
      <AuthCard
        title="Two-factor authentication"
        subtitle="Enter the 6-digit code from your authenticator app."
      >
        <div className="flex flex-col gap-5">
          <Digits />
          <div className="flex justify-between" style={{ fontSize: 12.5 }}>
            <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 500 }}>
              Use a backup code
            </Link>
            <span style={{ color: 'var(--text-tertiary)' }}>
              Resend in <span className="num">0:30</span>
            </span>
          </div>
          <Button size="lg" disabled>
            Verify
          </Button>
        </div>
      </AuthCard>
    </AuthShell>
  );
}

function Digits() {
  return (
    <div className="flex justify-center gap-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="inline-flex items-center justify-center"
          style={{
            width: 44,
            height: 56,
            borderRadius: 6,
            border: `1.5px solid ${i === 0 ? 'var(--accent)' : 'var(--border-default)'}`,
            background: 'var(--bg-surface)',
            fontSize: 24,
            fontWeight: 600,
            fontVariantNumeric: 'tabular-nums',
            color: 'var(--text-primary)',
            boxShadow: i === 0 ? '0 0 0 3px rgba(15,122,78,.16)' : 'none',
          }}
        />
      ))}
    </div>
  );
}
