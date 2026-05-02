import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { findPurchaseOrder, purchaseOrders } from '@/lib/mock/purchase';

export function usePurchaseOrders() {
  return useQuery({
    queryKey: ['purchase', 'orders'],
    queryFn: () => fakeFetch([...purchaseOrders]),
  });
}

export function usePurchaseOrder(id: string | undefined) {
  return useQuery({
    queryKey: ['purchase', 'orders', id],
    enabled: id !== undefined,
    queryFn: () => fakeFetch(() => (id ? (findPurchaseOrder(id) ?? null) : null)),
  });
}
