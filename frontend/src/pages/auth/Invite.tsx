import { useNavigate } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Monogram } from '@/components/ui/monogram';

/*
  Invite — visual port of fabric-2/project/shell-screens.jsx :: InviteAccept.
  Click-dummy: Accept routes to /onboarding (in real flow it'd skip
  onboarding entirely and land on /login since the inviter already set
  up the org/firm — but for the click-dummy this is the only way to
  reach onboarding without changing copy on the Login page).
*/
export default function Invite() {
  const navigate = useNavigate();

  return (
    <AuthShell>
      <AuthCard>
        <div className="mb-4 flex items-center gap-3">
          <Monogram initials="RT" size={44} tone="accent" />
          <div className="min-w-0 flex-1">
            <div
              className="uppercase"
              style={{
                fontSize: 11,
                color: 'var(--text-tertiary)',
                letterSpacing: '.06em',
              }}
            >
              You've been invited to
            </div>
            <div className="mt-0.5" style={{ fontSize: 17, fontWeight: 600 }}>
              Rajesh Textiles, Surat
            </div>
          </div>
        </div>
        <div
          className="flex flex-col gap-2"
          style={{
            padding: 14,
            borderRadius: 8,
            background: 'var(--bg-sunken)',
            border: '1px solid var(--border-subtle)',
            fontSize: 13,
          }}
        >
          <Row label="Role granted" value="Accountant" bold />
          <Row label="Invited by" value="Rajesh Patel · Owner" />
          <Row label="Permissions" value="Sales · Accounts · Reports" />
          <Row label="Expires" value={<span className="num">04-May-2026</span>} />
        </div>
        <div className="mt-4 flex gap-2">
          <Button onClick={() => navigate('/onboarding')}>Accept & set password</Button>
          <Button variant="ghost" onClick={() => navigate('/login')}>
            Decline
          </Button>
        </div>
      </AuthCard>
    </AuthShell>
  );
}

interface RowProps {
  label: string;
  value: React.ReactNode;
  bold?: boolean;
}

function Row({ label, value, bold }: RowProps) {
  return (
    <div className="flex justify-between">
      <span style={{ color: 'var(--text-tertiary)' }}>{label}</span>
      <span style={{ fontWeight: bold ? 600 : 400 }}>{value}</span>
    </div>
  );
}
