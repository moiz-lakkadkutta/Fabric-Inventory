import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { daybookEntries, gstrRows, pnlRows, stockRows, tbRows } from '@/lib/mock/reports';

export function usePnL() {
  return useQuery({
    queryKey: ['reports', 'pnl'],
    queryFn: () => fakeFetch([...pnlRows]),
  });
}

export function useTrialBalance() {
  return useQuery({
    queryKey: ['reports', 'tb'],
    queryFn: () => fakeFetch([...tbRows]),
  });
}

export function useGstr1() {
  return useQuery({
    queryKey: ['reports', 'gstr1'],
    queryFn: () => fakeFetch([...gstrRows]),
  });
}

export function useStockReport() {
  return useQuery({
    queryKey: ['reports', 'stock'],
    queryFn: () => fakeFetch([...stockRows]),
  });
}

export function useDaybook() {
  return useQuery({
    queryKey: ['reports', 'daybook'],
    queryFn: () => fakeFetch([...daybookEntries]),
  });
}
