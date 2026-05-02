import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';

import { cn } from '@/lib/utils';

// Taana button — sizes 32 / 40 / 48px, tracking tightened, radius scales up.
// Variants map to shadcn-compat aliases, which point at Taana brand tokens.
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium tracking-[-0.005em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-ring) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg-canvas) disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-(--accent) text-(--accent-text) hover:bg-(--accent-hover) active:bg-(--accent-pressed)',
        destructive:
          'bg-(--danger) text-(--text-inverse) hover:bg-(--danger)/90 active:bg-(--danger-text)',
        outline:
          'border border-(--border-default) bg-(--bg-surface) text-(--text-primary) hover:bg-(--bg-sunken) hover:border-(--border-strong)',
        secondary: 'bg-(--bg-sunken) text-(--text-primary) hover:bg-(--bg-sunken)/80',
        ghost: 'text-(--text-primary) hover:bg-(--bg-sunken)',
        link: 'text-(--accent) underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 rounded-md px-3 text-[13px] gap-1.5 [&_svg]:size-3.5',
        default: 'h-10 rounded-md px-4 text-sm [&_svg]:size-4',
        lg: 'h-12 rounded-lg px-5 text-[15px] gap-2.5 [&_svg]:size-4',
        icon: 'h-10 w-10 rounded-md [&_svg]:size-4',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
