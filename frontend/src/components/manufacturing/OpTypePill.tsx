/*
 * OpTypePill — operation_type colour-coded pill.
 *
 * The seven OperationType enum values (WEAVING, DYEING, EMBROIDERY,
 * STITCHING, QC, PACKING, OTHER) each get a sibling-palette pill that
 * harmonises with the kanban PHASE_TOKENS already on canvas — see
 * docs/design/phase6/phase6-shared.jsx `OP_TYPE_TOK` for the source of
 * truth that this file mirrors verbatim. Reused across the manufacturing
 * masters surface (Operations list / Create dialog + soon BOM / Routing
 * pages) so the kanban → master tabs cross-reference visually.
 *
 * Designed to be drop-in: no page-state coupling, no context dependency,
 * accepts only the `type` enum + a `size` knob. Renders an inline pill
 * with a fixed-colour dot + uppercase label.
 */

import type { components } from '@/types/api';

export type OperationType = components['schemas']['OperationType'];

interface OpTypeToken {
  fg: string;
  bg: string;
  accent: string;
  label: string;
}

/**
 * Per-operation-type pill palette — copied verbatim from
 * docs/design/phase6/phase6-shared.jsx `OP_TYPE_TOK`. The hex values are
 * approved palette siblings of the existing kanban PHASE_TOKENS — do
 * not invent new chromas here.
 */
export const OP_TYPE_TOK: Record<OperationType, OpTypeToken> = {
  // info slate
  WEAVING: { fg: '#3F4C5A', bg: '#E4E7EB', accent: '#3F4C5A', label: 'Weaving' },
  // terracotta — sibling of warning
  DYEING: { fg: '#7A4A1F', bg: '#F2DFC9', accent: '#9B5A3D', label: 'Dyeing' },
  // warning
  EMBROIDERY: { fg: '#6B4309', bg: '#F5E8D1', accent: '#A26710', label: 'Embroidery' },
  // accent
  STITCHING: { fg: '#0A4A2B', bg: '#D7E9DF', accent: '#0F7A4E', label: 'Stitching' },
  // success
  QC: { fg: '#0A4A2B', bg: '#DDEFE4', accent: '#137A48', label: 'QC' },
  // packed — neutral warm
  PACKING: { fg: '#605D52', bg: '#EAE7DD', accent: '#605D52', label: 'Packing' },
  OTHER: { fg: '#5C5A52', bg: '#EFEDE6', accent: '#8A8880', label: 'Other' },
};

interface OpTypePillProps {
  type: OperationType | null | undefined;
  size?: 'sm' | 'md';
}

export function OpTypePill({ type, size = 'sm' }: OpTypePillProps) {
  // Null / unknown types fall back to OTHER so the column always
  // renders a pill — the alternative (rendering nothing) makes the
  // table look broken when a legacy row has no operation_type set.
  const tok = OP_TYPE_TOK[type ?? 'OTHER'] ?? OP_TYPE_TOK.OTHER;
  return (
    <span
      data-testid="op-type-pill"
      data-op-type={type ?? 'OTHER'}
      className="inline-flex items-center uppercase"
      style={{
        gap: 6,
        height: size === 'sm' ? 22 : 26,
        padding: size === 'sm' ? '0 8px' : '0 10px',
        borderRadius: 4,
        background: tok.bg,
        color: tok.fg,
        fontSize: size === 'sm' ? 11 : 12,
        fontWeight: 600,
        letterSpacing: '0.04em',
        whiteSpace: 'nowrap',
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: tok.accent,
          flexShrink: 0,
        }}
      />
      {tok.label}
    </span>
  );
}
