// Stage taxonomy used by both the StagesTimeline component and the
// stock-mix bar on the Inventory list. Phase enables grouping
// (procurement -> production -> dispatch) and colour-coding.

export type StageId =
  | 'RAW'
  | 'CUT'
  | 'AT_EMBROIDERY'
  | 'QC_PENDING'
  | 'AT_STITCHING'
  | 'FINISHED'
  | 'PACKED';

export type StagePhase = 'PROCURE' | 'PRODUCE' | 'DISPATCH';

export interface StageMeta {
  id: StageId;
  label: string;
  phase: StagePhase;
}

export const STAGE_META: Record<StageId, StageMeta> = {
  RAW: { id: 'RAW', label: 'Raw', phase: 'PROCURE' },
  CUT: { id: 'CUT', label: 'Cut', phase: 'PRODUCE' },
  AT_EMBROIDERY: { id: 'AT_EMBROIDERY', label: 'At embroidery', phase: 'PRODUCE' },
  QC_PENDING: { id: 'QC_PENDING', label: 'QC pending', phase: 'PRODUCE' },
  AT_STITCHING: { id: 'AT_STITCHING', label: 'At stitching', phase: 'PRODUCE' },
  FINISHED: { id: 'FINISHED', label: 'Finished', phase: 'DISPATCH' },
  PACKED: { id: 'PACKED', label: 'Packed', phase: 'DISPATCH' },
};

export const PHASE_COLOR: Record<StagePhase, { bg: string; fg: string }> = {
  PROCURE: { bg: 'var(--info-subtle)', fg: 'var(--info-text)' },
  PRODUCE: { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  DISPATCH: { bg: 'var(--accent-subtle)', fg: 'var(--accent)' },
};
