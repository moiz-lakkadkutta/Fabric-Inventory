import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { findLot, lots, skuRows } from '@/lib/mock/inventory';

export function useSkus() {
  return useQuery({
    queryKey: ['inventory', 'skus'],
    queryFn: () => fakeFetch([...skuRows]),
  });
}

export function useLots() {
  return useQuery({
    queryKey: ['inventory', 'lots'],
    queryFn: () => fakeFetch([...lots]),
  });
}

export function useLot(lotId: string | undefined) {
  return useQuery({
    queryKey: ['inventory', 'lots', lotId],
    enabled: lotId !== undefined,
    queryFn: () => fakeFetch(() => (lotId ? (findLot(lotId) ?? null) : null)),
  });
}
