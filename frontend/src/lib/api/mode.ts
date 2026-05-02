/*
 * VITE_API_MODE controls whether queries hit the live backend or the
 * click-dummy mock layer. Per Q6 of the integration plan, both branches
 * stay in the source tree; Vite tree-shakes the unused one based on
 * the literal `import.meta.env.VITE_API_MODE` at build time.
 *
 * Defaults to "mock" so accidental imports keep the click-dummy
 * working. Production builds set VITE_API_MODE=live.
 */

const RAW = import.meta.env.VITE_API_MODE;

export const API_MODE: 'mock' | 'live' = RAW === 'live' ? 'live' : 'mock';

export const IS_LIVE = API_MODE === 'live';
export const IS_MOCK = API_MODE === 'mock';
