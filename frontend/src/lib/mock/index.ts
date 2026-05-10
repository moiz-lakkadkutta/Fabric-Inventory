// Single import surface for the mock layer.
//
// Pure formatters (`formatINR`, `formatINRCompact`, `formatDateShort`,
// `formatRelative`, `formatAgeing`, …) live at `@/lib/format` per
// CUT-004 — they are mock-mode-agnostic and should not be reached
// through this barrel.
//
// `currentUser`, `firms`, and `defaultFirm` from `./identity` are
// `@deprecated`; they remain as test fixtures + seed data for the
// fakeFetch mock branch only. Production / live-mode code reads
// identity from `authStore.me` via `useMe()`.

export * from './types';
export * from './identity';
export * from './parties';
export * from './items';
export * from './invoices';
export * from './kpis';
