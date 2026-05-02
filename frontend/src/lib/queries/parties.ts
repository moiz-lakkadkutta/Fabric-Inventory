import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { customers, parties } from '@/lib/mock/parties';

export function useParties() {
  return useQuery({
    queryKey: ['parties'],
    queryFn: () => fakeFetch([...parties]),
  });
}

export function useCustomers() {
  return useQuery({
    queryKey: ['parties', 'customers'],
    queryFn: () => fakeFetch([...customers]),
  });
}
