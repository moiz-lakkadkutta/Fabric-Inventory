import '@testing-library/jest-dom/vitest';

import { setMockApiDelay } from '@/lib/mock/api';

// Tests run with no artificial delay so they don't have to babysit
// pending UI; each query still resolves in a microtask, so the
// initial-render loading state remains observable.
setMockApiDelay(0);
