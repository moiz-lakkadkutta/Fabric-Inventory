import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <p className="text-sm text-[--color-muted-foreground]">
          Phase 1 scaffold. Real KPIs land in TASK-026 after the inventory + accounting services
          exist.
        </p>
      </header>
      <Card className="max-w-md">
        <CardHeader>
          <CardTitle>Welcome</CardTitle>
          <CardDescription>shadcn/ui Button + Card smoke test.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
        </CardContent>
      </Card>
    </div>
  );
}
