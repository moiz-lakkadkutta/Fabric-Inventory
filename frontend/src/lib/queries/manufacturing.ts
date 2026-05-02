import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { manufacturingOrders } from '@/lib/mock/manufacturing';

export function useManufacturingOrders() {
  return useQuery({
    queryKey: ['manufacturing', 'orders'],
    queryFn: () => fakeFetch([...manufacturingOrders]),
  });
}
