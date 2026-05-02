import * as React from 'react';

import { cn } from '@/lib/utils';

type InputState = 'default' | 'focus' | 'error' | 'disabled';

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  state?: InputState;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
  icon?: React.ReactNode;
}

const wrapperBase: React.CSSProperties = {
  height: 40,
  width: '100%',
  borderRadius: 6,
  background: 'var(--bg-surface)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border-default)',
  display: 'flex',
  alignItems: 'center',
  transition: 'border-color .15s ease, box-shadow .15s ease',
};

function wrapperFor(state: InputState): React.CSSProperties {
  if (state === 'focus') {
    return {
      ...wrapperBase,
      borderColor: 'var(--accent)',
      boxShadow: '0 0 0 3px rgba(15,122,78,.16)',
    };
  }
  if (state === 'error') {
    return {
      ...wrapperBase,
      borderColor: 'var(--danger)',
      boxShadow: '0 0 0 3px rgba(181,49,30,.14)',
    };
  }
  if (state === 'disabled') {
    return {
      ...wrapperBase,
      background: 'var(--bg-sunken)',
      color: 'var(--text-disabled)',
      borderColor: 'var(--border-subtle)',
      cursor: 'not-allowed',
    };
  }
  return wrapperBase;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    { state: explicitState, prefix, suffix, icon, disabled, className, onFocus, onBlur, ...rest },
    ref,
  ) => {
    const [focused, setFocused] = React.useState(false);
    const state: InputState =
      explicitState ?? (disabled ? 'disabled' : focused ? 'focus' : 'default');

    return (
      <div style={wrapperFor(state)} className={cn(className)}>
        {prefix && (
          <span
            style={{
              paddingLeft: 12,
              paddingRight: 10,
              marginRight: 4,
              color: 'var(--text-tertiary)',
              fontSize: 14,
              borderRight: '1px solid var(--border-subtle)',
              height: '70%',
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            {prefix}
          </span>
        )}
        {icon && (
          <span
            style={{
              paddingLeft: 12,
              color: 'var(--text-tertiary)',
              display: 'inline-flex',
            }}
          >
            {icon}
          </span>
        )}
        <input
          ref={ref}
          disabled={disabled}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          {...rest}
          style={{
            flex: 1,
            background: 'transparent',
            border: 0,
            outline: 'none',
            padding: prefix ? '0 12px 0 4px' : '0 12px',
            fontFamily: 'inherit',
            fontSize: 14,
            color: 'inherit',
            fontVariantNumeric: 'tabular-nums',
          }}
        />
        {suffix && (
          <span
            style={{
              paddingRight: 12,
              color: 'var(--text-tertiary)',
              fontSize: 13,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            {suffix}
          </span>
        )}
      </div>
    );
  },
);
Input.displayName = 'Input';
