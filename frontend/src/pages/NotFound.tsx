import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center space-y-4">
        <h2 className="text-3xl font-semibold">404 — Page not found</h2>
        <p className="text-sm text-[--color-muted-foreground]">
          That route doesn&apos;t exist (yet).
        </p>
        <Button asChild>
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    </div>
  );
}
