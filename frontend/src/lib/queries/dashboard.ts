import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { activity, kpis } from '@/lib/mock/kpis';

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () =>
      fakeFetch({
        kpis: [...kpis],
        activity: [...activity],
      }),
  });
}
