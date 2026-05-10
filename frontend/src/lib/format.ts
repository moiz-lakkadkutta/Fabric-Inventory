/**
 * Pure formatting helpers — paise → display string, dates → Asia/Kolkata.
 *
 * Lives outside `@/lib/mock` (CUT-004) so production code paths can format
 * money / dates without importing the mock layer. The mock layer's
 * fixtures + fakeFetch helpers stay isolated; if/when the mock layer is
 * deleted entirely, these helpers stay where every page expects them.
 *
 * All money in this app is integer paise; never float.
 */

const lakh = 1_00_000_00; // ₹1,00,000 in paise
const crore = 1_00_00_000_00; // ₹1,00,00,000 in paise

/**
 * Render paise as a Lakh/Crore-aware ₹ string.
 *   125_000_00  → "₹1.25 L"
 *   2_50_00_000_00 → "₹2.50 Cr"
 *   45_30_00 → "₹4,530"
 */
export function formatINR(paise: number, opts: { compact?: boolean } = {}): string {
  const sign = paise < 0 ? '-' : '';
  const abs = Math.abs(paise);
  if (opts.compact && abs >= crore) {
    return `${sign}₹${(abs / crore).toFixed(2)} Cr`;
  }
  if (opts.compact && abs >= lakh) {
    return `${sign}₹${(abs / lakh).toFixed(2)} L`;
  }
  // Indian grouping: 12,34,567.89
  const rupees = abs / 100;
  return `${sign}₹${rupees.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Compact form. Always uses L/Cr above ₹1L. */
export function formatINRCompact(paise: number): string {
  return formatINR(paise, { compact: true });
}

/**
 * Render an ISO date as IST short. "2026-04-30" → "30 Apr".
 */
export function formatDateShort(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    timeZone: 'Asia/Kolkata',
  });
}

/** "30 Apr 2026" */
export function formatDateLong(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  });
}

/** Relative-ish: "2h ago", "yesterday", "3 days ago". */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const ms = now.getTime() - then.getTime();
  // Future timestamps (e.g. system clock behind mock TODAY in dev): fall back to date.
  if (ms < 0) return formatDateShort(iso);
  const mins = Math.round(ms / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  return formatDateShort(iso);
}

/** "30+ days" / "5 days" / "Today" / "Due in 3 days" */
export function formatAgeing(days: number, status?: string): string {
  if (status === 'PAID') return 'Settled';
  if (status === 'CANCELLED') return '—';
  if (days === 0) return 'Due today';
  if (days < 0) return `Due in ${Math.abs(days)}d`;
  return `${days}d overdue`;
}

/**
 * Derive 1-2-letter avatar initials from an email address.
 *
 *   "audit@audit.example" → "AU"
 *   "moiz.p@example.com"  → "MP"
 *   "x@y.z"               → "X"
 *
 * Used by the topbar / user menu when /auth/me returns an email but no
 * `legal_name`. Pure helper — no DOM, no React.
 */
export function getInitialsFromEmail(email: string | null | undefined): string {
  if (!email) return '?';
  const local = email.split('@')[0] ?? '';
  // Split on common separators.
  const parts = local.split(/[._\-+]/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) {
    const word = parts[0];
    if (word.length >= 2) return word.slice(0, 2).toUpperCase();
    return word[0].toUpperCase();
  }
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
