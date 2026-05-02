// shell-screens.jsx — App shell + 8 auth/onboarding screens.
// Each rendered as a labeled section on the canvas.

const { useState: useStateScr } = React;

/* ── Frame: a labeled device frame around any rendered chunk ── */
function Frame({ label, sub, w, h, children, scrollable }) {
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', letterSpacing: '.04em' }}>{label}</span>
        {sub && <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>· {sub}</span>}
      </div>
      <div style={{
        width: w, height: h,
        background: 'var(--bg-canvas)',
        border: '1px solid var(--border-default)',
        borderRadius: 12, overflow: 'hidden',
        boxShadow: 'var(--shadow-1)',
      }}>
        <div style={{ width: '100%', height: '100%', overflow: scrollable ? 'auto' : 'hidden' }}>
          {children}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   APP SHELL — desktop / tablet / mobile + firm switcher open
───────────────────────────────────────────────────────────── */

function ShellMain({ device }) {
  const stub = (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexDirection: 'column', gap: 8, padding: 24, minHeight: 0,
    }}>
      <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Slot</div>
      <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>‹Screen content›</div>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>Every screen renders here.</div>
    </div>
  );

  const ph = (
    <PageHeader
      title="New Invoice"
      pill={<Pill kind="draft">Draft</Pill>}
      sub="Tax invoice · Rajesh Textiles, Surat · FY 2025-26"
      secondary={<Button variant="secondary" size="md">Save draft</Button>}
      primary={<Button variant="primary" size="md" icon={<Icon name="check" size={14} />}>Finalize & print</Button>}
    />
  );

  if (device === 'desktop') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <TopBar device="desktop" firmOpen={false} />
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <Sidebar collapsed={false} />
          <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-canvas)' }}>
            {ph}
            {stub}
          </main>
        </div>
      </div>
    );
  }
  if (device === 'tablet') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <TopBar device="tablet" />
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <Sidebar collapsed={true} />
          <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-canvas)' }}>
            {ph}
            {stub}
          </main>
        </div>
      </div>
    );
  }
  // mobile
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <TopBar device="mobile" />
      <div style={{
        height: 56, padding: '0 16px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <Icon name="arrow-right" size={16} color="var(--text-secondary)" />
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, whiteSpace: 'nowrap' }}>New invoice</h1>
          <Pill kind="draft">Draft</Pill>
        </div>
        <Icon name="more" size={18} color="var(--text-secondary)" />
      </div>
      <div style={{ flex: 1, minHeight: 0, background: 'var(--bg-canvas)', display: 'flex', flexDirection: 'column' }}>
        {stub}
      </div>
      <BottomNav active="sales" />
    </div>
  );
}

function ShellSection() {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32, alignItems: 'flex-start' }}>
      <Frame label="Desktop · 1440" sub="240 sidebar + 56 top bar" w={1100} h={620}>
        <ShellMain device="desktop" />
      </Frame>
      <Frame label="Tablet · 1024" sub="64 icon rail" w={760} h={520}>
        <ShellMain device="tablet" />
      </Frame>
      <Frame label="Mobile · 390" sub="bottom nav, 48 top bar" w={360} h={620}>
        <ShellMain device="mobile" />
      </Frame>
      <Frame label="Firm switcher · open" sub="popover off top bar" w={420} h={420}>
        <div style={{ padding: 20, background: 'var(--bg-canvas)', height: '100%' }}>
          <FirmSwitcher inline />
        </div>
      </Frame>
      <Frame label="Firm switcher · mobile" sub="bottom sheet" w={360} h={420}>
        <div style={{ padding: 0, background: 'rgba(20,20,18,.32)', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
          <FirmSwitcher inline mobile />
        </div>
      </Frame>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   AUTH FRAME — used by login / mfa / forgot / invite
───────────────────────────────────────────────────────────── */

function AuthFrame({ children, w = 460, h = 560, weave = true }) {
  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: 'var(--bg-canvas)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      overflow: 'hidden',
    }}>
      {weave && (
        <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.04 }} aria-hidden="true">
          <defs>
            <pattern id={`weave-${w}-${h}-${Math.random().toString(36).slice(2,5)}`} width="24" height="24" patternUnits="userSpaceOnUse">
              <line x1="3"  y1="0" x2="3"  y2="24" stroke="#1A1A17" strokeWidth="1" />
              <line x1="9"  y1="0" x2="9"  y2="24" stroke="#1A1A17" strokeWidth="1" />
              <line x1="15" y1="0" x2="15" y2="24" stroke="#1A1A17" strokeWidth="1" />
              <line x1="21" y1="0" x2="21" y2="24" stroke="#1A1A17" strokeWidth="1" />
              <line x1="0" y1="6"  x2="24" y2="6"  stroke="#1A1A17" strokeWidth="1" />
              <line x1="0" y1="18" x2="24" y2="18" stroke="#1A1A17" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="#1A1A17" fillOpacity="0.04" />
          <rect width="100%" height="100%" style={{ fill: '#1A1A17', opacity: 0.05 }} />
        </svg>
      )}
      {weave && <WeaveLayer />}
      <div style={{ width: w, position: 'relative', zIndex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 24 }}>
          <Wordmark size={28} />
        </div>
        {children}
        <div style={{ marginTop: 20, fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'center' }}>
          taana · v0.1 · audit-grade ledger
        </div>
      </div>
    </div>
  );
}

function WeaveLayer() {
  return (
    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.05 }} aria-hidden="true">
      <defs>
        <pattern id="auth-weave" width="32" height="32" patternUnits="userSpaceOnUse">
          {[0,1,2,3,4].map(i => (
            <line key={'v'+i} x1={4 + i*7} y1="0" x2={4 + i*7} y2="32" stroke="#1A1A17" strokeWidth="1" />
          ))}
          <line x1="0" y1="8"  x2="32" y2="8"  stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="24" x2="32" y2="24" stroke="#1A1A17" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#auth-weave)" />
    </svg>
  );
}

function AuthCard({ children, title, subtitle, pad = 32 }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 12, padding: pad, boxShadow: 'var(--shadow-2)',
    }}>
      {(title || subtitle) && (
        <div style={{ marginBottom: 24 }}>
          {title && <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em' }}>{title}</h2>}
          {subtitle && <p style={{ fontSize: 13.5, color: 'var(--text-secondary)', margin: '6px 0 0', lineHeight: 1.5 }}>{subtitle}</p>}
        </div>
      )}
      {children}
    </div>
  );
}

/* 1 — LOGIN ──────────────────────────────────────────────── */
function LoginIdle() {
  return (
    <AuthCard title="Sign in to your books" subtitle="Use the email associated with your firm.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Email">
          <Input value="moiz@rajeshtextiles.in" icon={<Icon name="mail" size={14} />} />
        </Field>
        <Field label="Password">
          <Input value="••••••••••••" suffix={<Icon name="eye" size={14} />} />
        </Field>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
          <span style={{
            width: 16, height: 16, borderRadius: 4,
            border: '1.5px solid var(--accent)', background: 'var(--accent)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}><Icon name="check" size={12} color="#FAFAF7" /></span>
          Remember this device for 30 days
        </label>
        <Button variant="primary" size="lg">Sign in</Button>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4, alignItems: 'center' }}>
          <a style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}>Forgot password?</a>
          <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            New here? <a style={{ color: 'var(--accent)', fontWeight: 500 }}>Set up your business</a>
          </span>
        </div>
      </div>
    </AuthCard>
  );
}

function LoginLoading() {
  return (
    <AuthCard title="Sign in to your books" subtitle="Use the email associated with your firm.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Email"><Input state="disabled" value="moiz@rajeshtextiles.in" /></Field>
        <Field label="Password"><Input state="disabled" value="••••••••••••" /></Field>
        <Button variant="primary" size="lg" icon={
          <span style={{ display: 'inline-flex', animation: 'taanaSpin 0.9s linear infinite' }}>
            <Icon name="spinner" size={14} color="#FAFAF7" />
          </span>
        }>Signing in…</Button>
      </div>
    </AuthCard>
  );
}

function LoginError() {
  return (
    <AuthCard title="Sign in to your books" subtitle="Use the email associated with your firm.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Email">
          <Input value="moiz@rajeshtextiles.in" icon={<Icon name="mail" size={14} />} />
        </Field>
        <Field label="Password" state="error" error="Email or password is incorrect. Forgot password?">
          <Input state="error" value="••••••••" />
        </Field>
        <Button variant="primary" size="lg">Sign in</Button>
      </div>
    </AuthCard>
  );
}

/* 2 — MFA ────────────────────────────────────────────────── */
function MfaDigits({ value = '839154', errorIdx = -1, focusIdx = -1 }) {
  const digits = value.padEnd(6, ' ').split('').slice(0, 6);
  return (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
      {digits.map((d, i) => {
        const filled = d.trim() !== '';
        const errored = errorIdx === i || (errorIdx === -2 && filled);
        const focused = focusIdx === i;
        return (
          <div key={i} style={{
            width: 44, height: 56, borderRadius: 6,
            border: '1.5px solid ' + (errored ? 'var(--danger)' : focused ? 'var(--accent)' : 'var(--border-default)'),
            background: errored ? 'var(--danger-subtle)' : 'var(--bg-surface)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
            color: errored ? 'var(--danger-text)' : 'var(--text-primary)',
            boxShadow: focused ? '0 0 0 3px rgba(15,122,78,.16)' : 'none',
          }}>{d.trim()}</div>
        );
      })}
    </div>
  );
}

function MfaIdle() {
  return (
    <AuthCard title="Two-factor authentication" subtitle="Enter the 6-digit code from your authenticator app.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <MfaDigits value="    " focusIdx={0} />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
          <a style={{ color: 'var(--accent)', fontWeight: 500 }}>Use a backup code</a>
          <span style={{ color: 'var(--text-tertiary)' }}>Resend in 0:30</span>
        </div>
        <Button variant="primary" size="lg" state="disabled">Verify</Button>
      </div>
    </AuthCard>
  );
}

function MfaError() {
  return (
    <AuthCard title="Two-factor authentication" subtitle="Enter the 6-digit code from your authenticator app.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <MfaDigits value="839154" errorIdx={-2} />
        <div style={{
          padding: '10px 12px', background: 'var(--danger-subtle)',
          color: 'var(--danger-text)', borderRadius: 6,
          fontSize: 12.5, display: 'flex', gap: 8, alignItems: 'flex-start',
        }}>
          <Icon name="alert" size={14} color="var(--danger)" />
          <span>Code didn't match. <strong>2 tries left</strong> before this device is locked for 15 minutes.</span>
        </div>
        <Button variant="primary" size="lg">Try again</Button>
      </div>
    </AuthCard>
  );
}

function MfaSuccess() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
      <AuthCard pad={28}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, padding: '8px 8px 4px' }}>
          <div style={{
            width: 48, height: 48, borderRadius: 999, background: 'var(--accent-subtle)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Icon name="check" size={22} color="var(--accent)" />
          </div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Verified</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>Redirecting to dashboard…</div>
        </div>
      </AuthCard>
      {/* Toast */}
      <div style={{
        width: 360, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
        borderLeft: '3px solid var(--success)', borderRadius: 8, padding: '10px 14px',
        display: 'flex', gap: 10, alignItems: 'flex-start', boxShadow: 'var(--shadow-2)',
      }}>
        <Icon name="check-circle" size={16} color="var(--success)" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Signed in to Rajesh Textiles</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>Last sign-in 4 days ago from Surat.</div>
        </div>
      </div>
    </div>
  );
}

/* 3 — FORGOT PASSWORD ────────────────────────────────────── */
function ForgotStep1() {
  return (
    <AuthCard title="Reset your password" subtitle="Enter your email and we'll send a reset link.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Email">
          <Input value="moiz@rajeshtextiles.in" icon={<Icon name="mail" size={14} />} />
        </Field>
        <Button variant="primary" size="lg">Send reset link</Button>
        <a style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center' }}>
          Back to sign in
        </a>
      </div>
    </AuthCard>
  );
}

function ForgotStep2() {
  return (
    <AuthCard pad={28}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center' }}>
        <div style={{
          width: 48, height: 48, borderRadius: 999, background: 'var(--accent-subtle)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Icon name="mail" size={20} color="var(--accent)" />
        </div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>Check your email</div>
        <div style={{ fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.55, maxWidth: 320 }}>
          We sent a reset link to <strong style={{ color: 'var(--text-primary)' }}>m••••@rajeshtextiles.in</strong>. The link expires in 30 minutes.
        </div>
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>Didn't get it? Resend in <span className="num">0:45</span></span>
          <a style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}>Use a different email</a>
        </div>
      </div>
    </AuthCard>
  );
}

/* 4 — INVITE ACCEPT ──────────────────────────────────────── */
function InviteAccept() {
  return (
    <AuthCard pad={28}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
        <Monogram initials="RT" size={44} tone="accent" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>You've been invited to</div>
          <div style={{ fontSize: 17, fontWeight: 600, marginTop: 2 }}>Rajesh Textiles, Surat</div>
        </div>
      </div>
      <div style={{
        padding: 14, borderRadius: 8, background: 'var(--bg-sunken)',
        border: '1px solid var(--border-subtle)',
        display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Role granted</span>
          <span style={{ fontWeight: 600 }}>Accountant</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Invited by</span>
          <span>Rajesh Patel · Owner</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Permissions</span>
          <span>Sales · Accounts · Reports</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Expires</span>
          <span className="num">04-May-2026</span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
        <Button variant="primary" size="md">Accept & set password</Button>
        <Button variant="ghost" size="md">Decline</Button>
      </div>
    </AuthCard>
  );
}

/* 5/6/7 — ONBOARDING WIZARD ──────────────────────────────── */
function Stepper({ active }) {
  const steps = [
    { id: 0, label: 'Org' },
    { id: 1, label: 'Firm' },
    { id: 2, label: 'Opening balances' },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 24 }}>
      {steps.map((s, i) => {
        const done = i < active, here = i === active;
        return (
          <React.Fragment key={s.id}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 22, height: 22, borderRadius: 999,
                background: done ? 'var(--accent)' : here ? 'var(--bg-surface)' : 'var(--bg-sunken)',
                border: '1.5px solid ' + (done || here ? 'var(--accent)' : 'var(--border-default)'),
                color: done ? '#FAFAF7' : here ? 'var(--accent)' : 'var(--text-tertiary)',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700,
              }}>{done ? <Icon name="check" size={12} color="#FAFAF7" /> : (i + 1)}</div>
              <span style={{
                fontSize: 13, fontWeight: here ? 600 : 500,
                color: here ? 'var(--text-primary)' : done ? 'var(--text-secondary)' : 'var(--text-tertiary)',
                whiteSpace: 'nowrap',
              }}>{s.label}</span>
            </div>
            {i < steps.length - 1 && (
              <div style={{
                flex: 1, height: 1.5, margin: '0 14px',
                background: i < active ? 'var(--accent)' : 'var(--border-default)',
              }} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

function OnbOrg() {
  return (
    <div style={{
      width: 720, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 12, padding: 28,
    }}>
      <Stepper active={0} />
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 28 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em' }}>Tell us about your organisation</h2>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '4px 0 18px' }}>An org can hold one or more firms. You can add more firms later.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Organisation name" required>
              <Input value="Rajesh Patel Holdings" />
            </Field>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Contact email" required>
                <Input value="rajesh@rpholdings.in" icon={<Icon name="mail" size={14} />} />
              </Field>
              <Field label="Phone">
                <Input prefix="+91" value="98250 14728" />
              </Field>
            </div>
            <Field label="Country">
              <Input value="India" suffix={<Icon name="chevron-down" />} />
            </Field>
          </div>
        </div>
        <aside style={{
          background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)',
          borderRadius: 8, padding: 18,
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600, marginBottom: 8 }}>What's an org?</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
            Your org holds one or more firms. Each firm has its own books, invoice numbering, and GSTIN. Most users start with one firm and add more as the business grows.
          </div>
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border-default)', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Examples</div>
            <div style={{ fontSize: 12.5 }}><strong>Rajesh Patel Holdings</strong> → Rajesh Textiles · Patel Embroidery Works</div>
            <div style={{ fontSize: 12.5 }}><strong>Khan Trading Co.</strong> → one firm, GST-registered</div>
          </div>
        </aside>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--border-subtle)' }}>
        <Button variant="ghost" size="md">Cancel</Button>
        <Button variant="primary" size="md" iconRight={<Icon name="arrow-right" size={14} />}>Next: Add firm</Button>
      </div>
    </div>
  );
}

function OnbFirm() {
  return (
    <div style={{
      width: 720, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 12, padding: 28,
    }}>
      <Stepper active={1} />
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 28 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em' }}>Add your first firm</h2>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '4px 0 18px' }}>Each firm has its own books and invoice series.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Firm name (display)" required>
              <Input value="Rajesh Textiles, Surat" />
            </Field>
            <Field label="Tax regime" required>
              <div style={{ display: 'flex', gap: 8 }}>
                <SegOpt active label="GST registered" sub="Charge & reclaim GST" />
                <SegOpt label="Non-GST" sub="Below threshold or composition" />
              </div>
            </Field>
            <Field label="GSTIN" required hint="Auto-validates on blur">
              <Input value="24ABCDE1234F1Z5" suffix={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--success)' }}>
                  <Icon name="check-circle" size={14} color="var(--success)" />
                  <span style={{ fontSize: 11, fontWeight: 600 }}>Verified</span>
                </span>
              } />
            </Field>
            <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12 }}>
              <Field label="Legal name (auto-filled)">
                <Input state="disabled" value="Rajesh Patel Textiles Pvt Ltd" />
              </Field>
              <Field label="State of supply">
                <Input state="disabled" value="Gujarat (24)" />
              </Field>
            </div>
            <Field label="PAN" hint="Optional · used for TDS">
              <Input value="ABCDE1234F" />
            </Field>
          </div>
        </div>
        <aside style={{
          background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)',
          borderRadius: 8, padding: 18,
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600, marginBottom: 8 }}>GST or Non-GST</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
            Both are first-class. Non-GST firms still get full invoicing, ledgers, and inventory — just without tax fields. You can switch later if your turnover changes.
          </div>
          <div style={{ marginTop: 14, fontSize: 12, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Icon name="shield" size={12} color="var(--text-tertiary)" />
            <span>GSTIN validated against GSTN public registry.</span>
          </div>
        </aside>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--border-subtle)' }}>
        <Button variant="secondary" size="md" icon={<Icon name="arrow-right" size={14} color="currentColor" />}>Back</Button>
        <Button variant="primary" size="md" iconRight={<Icon name="arrow-right" size={14} />}>Next: Opening balances</Button>
      </div>
    </div>
  );
}

function SegOpt({ active, label, sub }) {
  return (
    <div style={{
      flex: 1, padding: 14, borderRadius: 8,
      border: '1.5px solid ' + (active ? 'var(--accent)' : 'var(--border-default)'),
      background: active ? 'var(--accent-subtle)' : 'var(--bg-surface)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          width: 16, height: 16, borderRadius: 999,
          border: '1.5px solid ' + (active ? 'var(--accent)' : 'var(--border-strong)'),
          background: active ? 'var(--accent)' : 'transparent',
          boxShadow: active ? 'inset 0 0 0 3px var(--bg-surface)' : 'none',
        }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: active ? 'var(--accent)' : 'var(--text-primary)' }}>{label}</span>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4, paddingLeft: 24 }}>{sub}</div>
    </div>
  );
}

function OnbOpening() {
  const phases = ['Parsing file', 'Validating', 'Preview ready', 'Commit'];
  const activeIdx = 2;
  return (
    <div style={{
      width: 720, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 12, padding: 28,
    }}>
      <Stepper active={2} />
      <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em' }}>Bring in your opening balances</h2>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '4px 0 18px' }}>Pick how you'd like to start. You can change this within the first 30 days.</p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <RadioRow label="I'm new to the trade" sub="Skip — start with empty books." />
        <RadioRow active label="Import from Vyapar (.vyp)" sub="We parse parties, ledgers, and stock balances." extra={
          <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
            <div style={{
              border: '1.5px dashed var(--border-strong)', borderRadius: 8,
              padding: 18, background: 'var(--bg-sunken)',
              display: 'flex', alignItems: 'center', gap: 14,
            }}>
              <Icon name="upload-cloud" size={28} color="var(--accent)" />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>rajesh-textiles-2025-26.vyp</div>
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }} className="num">4.2 MB · uploaded 14:32</div>
              </div>
              <Button variant="ghost" size="sm">Replace</Button>
            </div>

            {/* Phase progress */}
            <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 0 }}>
              {phases.map((p, i) => {
                const done = i < activeIdx, here = i === activeIdx;
                return (
                  <React.Fragment key={p}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: 999,
                        background: done ? 'var(--accent)' : here ? 'var(--accent)' : 'var(--border-strong)',
                      }} />
                      <span style={{
                        fontSize: 12, fontWeight: here ? 600 : 500,
                        color: done ? 'var(--text-secondary)' : here ? 'var(--text-primary)' : 'var(--text-tertiary)',
                      }}>{p}</span>
                    </div>
                    {i < phases.length - 1 && (
                      <div style={{
                        flex: 1, height: 1.5, margin: '0 10px',
                        background: i < activeIdx ? 'var(--accent)' : 'var(--border-default)',
                      }} />
                    )}
                  </React.Fragment>
                );
              })}
            </div>

            {/* Reconciliation */}
            <div style={{
              marginTop: 14, padding: 14, borderRadius: 8,
              background: 'var(--success-subtle)', color: 'var(--success-text)',
              display: 'flex', gap: 12, alignItems: 'flex-start',
            }}>
              <Icon name="check-circle" size={16} color="var(--success)" />
              <div style={{ flex: 1, fontSize: 12.5, lineHeight: 1.55 }}>
                <div style={{ fontWeight: 600 }}>Reconciliation OK</div>
                Detected <span className="num">247</span> parties · <span className="num">89</span> ledgers · <span className="num">412</span> items.
                Trial-balance delta <span className="num">₹0.42</span> vs Vyapar (within tolerance).
              </div>
            </div>
          </div>
        } />
        <RadioRow label="Manual entry" sub="Type opening balances yourself." extra={null} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--border-subtle)' }}>
        <Button variant="secondary" size="md">Back</Button>
        <Button variant="primary" size="md">Commit & finish</Button>
      </div>
    </div>
  );
}

function RadioRow({ active, label, sub, extra }) {
  return (
    <div style={{
      padding: 16, borderRadius: 8,
      border: '1.5px solid ' + (active ? 'var(--accent)' : 'var(--border-default)'),
      background: active ? 'var(--bg-surface)' : 'var(--bg-surface)',
      boxShadow: active ? '0 0 0 3px var(--accent-subtle)' : 'none',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{
          width: 18, height: 18, borderRadius: 999,
          border: '1.5px solid ' + (active ? 'var(--accent)' : 'var(--border-strong)'),
          background: active ? 'var(--accent)' : 'transparent',
          boxShadow: active ? 'inset 0 0 0 3px var(--bg-surface)' : 'none',
          flexShrink: 0,
        }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: active ? 'var(--accent)' : 'var(--text-primary)' }}>{label}</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>
        </div>
      </div>
      {extra}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   CANVAS ROOT
───────────────────────────────────────────────────────────── */

function ScrSection({ id, title, sub, children }) {
  return (
    <div style={{ marginTop: 56 }}>
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'baseline', gap: 12, borderBottom: '1px solid var(--border-default)', paddingBottom: 10 }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--accent)', letterSpacing: '.04em', fontWeight: 600 }}>{id}</span>
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em', whiteSpace: 'nowrap' }}>{title}</h2>
        {sub && <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>{sub}</span>}
      </div>
      {children}
    </div>
  );
}

const ANTIPATTERNS_2 = [
  ['"Welcome back!" / "Hi Moiz!" greetings',         'Honoured', 'No greeting on login or shell. User name only in monogram chip.'],
  ['Marketing strapline on login card',              'Honoured', 'Card subtitle says "Use the email associated with your firm" — purely functional.'],
  ['Social-login buttons',                           'Honoured', 'None present.'],
  ['3-column "feature card" landing in onboarding',  'Honoured', 'Wizard is single-column form + right-rail explanation.'],
  ['Coloured-icon-circle on wizard steps',           'Honoured', 'Stepper uses outlined numerals; success state uses one accent ring only.'],
  ['Centred modals on mobile',                       'Honoured', 'Firm switcher renders as bottom sheet on the 390 frame.'],
];

function CanvasRoot({ device }) {
  const widths = { desktop: 1440, tablet: 1024, mobile: 390 };
  const W = widths[device];
  return (
    <div style={{
      width: W, minHeight: 1800,
      background: 'var(--bg-canvas)',
      padding: device === 'mobile' ? 20 : device === 'tablet' ? 32 : 56,
      margin: '0 auto',
      boxShadow: '0 8px 24px rgba(20,20,18,.06)',
      borderRadius: 12,
      transition: 'width .3s ease',
    }}>
      {/* header */}
      <div style={{
        paddingBottom: 24, marginBottom: 32, borderBottom: '1px solid var(--border-default)',
        display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
      }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 8 }}>Phase 1 · Shell + Auth</div>
          <h1 style={{ fontSize: 32, fontWeight: 600, margin: 0, letterSpacing: '-0.018em', lineHeight: 1.15 }}>
            App shell, sign-in, and onboarding<br/>
            <span style={{ color: 'var(--text-tertiary)' }}>the chrome every screen sits inside</span>
          </h1>
        </div>
        <div style={{ textAlign: 'right' }}>
          <Wordmark size={24} />
          <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 6 }}>
            27-Apr-2026 · v0.1
          </div>
        </div>
      </div>

      <ScrSection id="SHELL" title="App shell" sub="Top bar · sidebar · bottom nav · 1440 / 1024 / 390">
        <ShellSection />
      </ScrSection>

      <ScrSection id="SCR-AUTH-001" title="Login" sub="Idle · loading · error">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          <Frame label="Idle"    w={500} h={620}><AuthFrame><LoginIdle /></AuthFrame></Frame>
          <Frame label="Loading" w={500} h={620}><AuthFrame><LoginLoading /></AuthFrame></Frame>
          <Frame label="Error · inline" w={500} h={620}><AuthFrame><LoginError /></AuthFrame></Frame>
        </div>
      </ScrSection>

      <ScrSection id="SCR-AUTH-002" title="MFA / TOTP" sub="6-segmented input · auto-advance · paste-supported">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          <Frame label="Idle"    w={500} h={520}><AuthFrame h={500}><MfaIdle /></AuthFrame></Frame>
          <Frame label="Error · 2 tries left" w={500} h={520}><AuthFrame h={500}><MfaError /></AuthFrame></Frame>
          <Frame label="Success · auto-redirect" w={500} h={520}><AuthFrame h={500}><MfaSuccess /></AuthFrame></Frame>
        </div>
      </ScrSection>

      <ScrSection id="SCR-AUTH-003" title="Forgot password" sub="Two-step coaching">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          <Frame label="Step 1 · enter email" w={500} h={500}><AuthFrame h={480}><ForgotStep1 /></AuthFrame></Frame>
          <Frame label="Step 2 · check email" w={500} h={500}><AuthFrame h={480}><ForgotStep2 /></AuthFrame></Frame>
        </div>
      </ScrSection>

      <ScrSection id="SCR-AUTH-004" title="Invite accept" sub="Org wordmark · role · inviter">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          <Frame label="Card" w={500} h={520}><AuthFrame h={500}><InviteAccept /></AuthFrame></Frame>
        </div>
      </ScrSection>

      <ScrSection id="SCR-ONB-001" title="Onboarding · Org" sub="Wizard step 1 of 3">
        <div style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 32, display: 'flex', justifyContent: 'center' }}>
          <OnbOrg />
        </div>
      </ScrSection>

      <ScrSection id="SCR-ONB-002" title="Onboarding · First firm + GSTIN" sub="Wizard step 2 of 3 · async GSTIN validation">
        <div style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 32, display: 'flex', justifyContent: 'center' }}>
          <OnbFirm />
        </div>
      </ScrSection>

      <ScrSection id="SCR-ONB-003" title="Onboarding · Opening balances" sub="Wizard step 3 of 3 · Vyapar import">
        <div style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 32, display: 'flex', justifyContent: 'center' }}>
          <OnbOpening />
        </div>
      </ScrSection>

      <ScrSection id="SCR-ONB-DONE" title="Wizard complete" sub="Final-step success">
        <div style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 48, display: 'flex', justifyContent: 'center' }}>
          <div style={{
            width: 520, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 12, padding: 32, textAlign: 'center',
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: 999, background: 'var(--accent-subtle)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px',
            }}>
              <TaanaMark size={28} color="var(--accent)" />
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: 0, letterSpacing: '-0.012em' }}>taana is ready.</h2>
            <p style={{ fontSize: 13.5, color: 'var(--text-secondary)', marginTop: 8, marginBottom: 24, lineHeight: 1.5 }}>
              Imported 247 parties, 89 ledgers, 412 items. Your books are reconciled to the rupee.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <Button variant="primary" size="md">Take me to the dashboard</Button>
              <Button variant="ghost" size="md">Show me around first</Button>
            </div>
          </div>
        </div>
      </ScrSection>

      {/* Self-review */}
      <div style={{
        marginTop: 56, background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
        borderRadius: 12, padding: 28,
      }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Self-review</h3>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4, marginBottom: 18 }}>Three checks called out in the brief.</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24 }}>
          <ReviewItem
            num="1"
            check="Tablet hit-targets ≥ 40px"
            verdict="Pass"
            note="Top bar buttons 36px (desktop) → upsized to 40px on tablet via responsive height. Sidebar items are 40px tall throughout. Bottom-nav items 56px each, full column. Form fields 40px. CTAs default md=40, lg=48 on tablet."
          />
          <ReviewItem
            num="2"
            check="GSTIN truncates gracefully"
            verdict="Pass with caveat"
            note="The firm-switcher trigger limits the GSTIN to maxWidth: 130px and truncates with an ellipsis at narrow widths. Inside the popover, GSTIN gets 60% of the row and ellipsises. Caveat: at exactly 1024 the trigger hides the GSTIN entirely (firm name only) — flagged for a future tooltip."
          />
          <ReviewItem
            num="3"
            check="Active sidebar item is unmistakable, no purple"
            verdict="Pass"
            note="Active state combines four affordances: emerald-subtle background, 2px emerald left border (flush to sidebar edge), emerald icon + label colour, and font-weight 600 vs 500 on inactive. Sub-nav reveals only under the active parent."
          />
        </div>

        <div style={{ marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: 14, fontWeight: 600, margin: 0, marginBottom: 10 }}>Anti-pattern audit</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr auto 2fr', columnGap: 16, rowGap: 8, alignItems: 'baseline' }}>
            {ANTIPATTERNS_2.map(([rule, status, note]) => (
              <React.Fragment key={rule}>
                <div style={{ fontSize: 13, color: 'var(--text-primary)' }}>{rule}</div>
                <div><Pill kind={status === 'Honoured' ? 'paid' : 'overdue'}>{status}</Pill></div>
                <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{note}</div>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewItem({ num, check, verdict, note }) {
  const ok = verdict.startsWith('Pass');
  return (
    <div style={{
      background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 600 }}>{num}</span>
        <Pill kind={ok ? 'paid' : 'overdue'}>{verdict}</Pill>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{check}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{note}</div>
    </div>
  );
}

Object.assign(window, { CanvasRoot });
