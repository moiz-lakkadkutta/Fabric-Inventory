import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';

interface ComingSoonDialogProps {
  open: boolean;
  onClose: () => void;
  feature: string;
  task?: string;
  detail?: React.ReactNode;
}

/*
  Standard "this lands later" dialog. Used for any action that doesn't
  yet have a real flow but needs to be reachable per the click-dummy
  T7 navigation audit. The dialog itself is the reachable destination.
*/
export function ComingSoonDialog({ open, onClose, feature, task, detail }: ComingSoonDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={feature}
      description="This action is wired in the click-dummy. The full flow lands in a later phase."
      footer={
        <Button variant="outline" onClick={onClose}>
          Got it
        </Button>
      }
    >
      <div
        className="space-y-2"
        style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}
      >
        {detail ?? (
          <p>
            Right now this opens this dialog so navigation feels complete. The real flow — full
            form, validation, posting — ships with the related backend task.
          </p>
        )}
        {task && (
          <p
            className="mono"
            style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 12 }}
          >
            Tracked in {task}
          </p>
        )}
      </div>
    </Dialog>
  );
}

/*
  Convenience hook: returns { triggerProps, dialog } so a button can
  spread props onto itself and the page just renders {dialog} once.

    const { triggerProps, dialog } = useComingSoon({ feature: 'Export CSV' });
    <Button {...triggerProps}>Export CSV</Button>
    {dialog}
*/
export function useComingSoon(opts: { feature: string; task?: string; detail?: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const triggerProps = { onClick: () => setOpen(true) };
  const dialog = (
    <ComingSoonDialog
      open={open}
      onClose={() => setOpen(false)}
      feature={opts.feature}
      task={opts.task}
      detail={opts.detail}
    />
  );
  return { triggerProps, dialog, open, close: () => setOpen(false) };
}
