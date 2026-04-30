interface PlaceholderProps {
  title: string;
  task?: string;
}

export default function Placeholder({ title, task }: PlaceholderProps) {
  return (
    <div className="space-y-3">
      <h2 className="text-2xl font-semibold">{title}</h2>
      <p className="text-sm text-(--color-muted-foreground)">
        Coming soon{task ? ` (${task})` : ''}.
      </p>
    </div>
  );
}
