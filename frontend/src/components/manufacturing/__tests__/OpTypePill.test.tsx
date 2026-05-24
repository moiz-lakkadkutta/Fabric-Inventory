/*
 * OpTypePill — palette + render tests.
 *
 * Each OperationType gets its own assertion: label text + background
 * colour. The hex values are pulled directly from OP_TYPE_TOK so the
 * test pins the export rather than re-declaring magic strings.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OP_TYPE_TOK, OpTypePill, type OperationType } from '@/components/manufacturing/OpTypePill';

const TYPES: OperationType[] = [
  'WEAVING',
  'DYEING',
  'EMBROIDERY',
  'STITCHING',
  'QC',
  'PACKING',
  'OTHER',
];

describe('OpTypePill', () => {
  it.each(TYPES)('renders the %s palette with correct label + bg', (type) => {
    const tok = OP_TYPE_TOK[type];
    const { unmount } = render(<OpTypePill type={type} />);
    const pill = screen.getByTestId('op-type-pill');
    // Label text matches the OP_TYPE_TOK label verbatim.
    expect(pill).toHaveTextContent(tok.label);
    // data-op-type pins the rendered enum, lets the dialog "preview"
    // panel + downstream pages re-query without sniffing className.
    expect(pill).toHaveAttribute('data-op-type', type);
    // Inline styles carry the approved palette hex values.
    expect(pill).toHaveStyle({
      background: tok.bg,
      color: tok.fg,
    });
    unmount();
  });

  it('falls back to OTHER when type is null', () => {
    render(<OpTypePill type={null} />);
    const pill = screen.getByTestId('op-type-pill');
    expect(pill).toHaveAttribute('data-op-type', 'OTHER');
    expect(pill).toHaveTextContent(OP_TYPE_TOK.OTHER.label);
  });

  it('renders larger size variant', () => {
    render(<OpTypePill type="STITCHING" size="md" />);
    const pill = screen.getByTestId('op-type-pill');
    expect(pill).toHaveStyle({ height: '26px' });
  });
});
