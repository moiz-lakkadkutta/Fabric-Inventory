import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { jobs, karigars } from '@/lib/mock/jobwork';

export function useKarigars() {
  return useQuery({
    queryKey: ['jobwork', 'karigars'],
    queryFn: () => fakeFetch([...karigars]),
  });
}

export function useJobs() {
  return useQuery({
    queryKey: ['jobwork', 'jobs'],
    queryFn: () => fakeFetch([...jobs]),
  });
}
