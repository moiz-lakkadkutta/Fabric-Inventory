import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { items } from '@/lib/mock/items';

export function useItems() {
  return useQuery({
    queryKey: ['items'],
    queryFn: () => fakeFetch([...items]),
  });
}
