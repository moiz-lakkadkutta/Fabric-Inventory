import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { receipts, vouchers } from '@/lib/mock/accounts';

export function useReceipts() {
  return useQuery({
    queryKey: ['accounts', 'receipts'],
    queryFn: () => fakeFetch([...receipts]),
  });
}

export function useVouchers() {
  return useQuery({
    queryKey: ['accounts', 'vouchers'],
    queryFn: () => fakeFetch([...vouchers]),
  });
}
