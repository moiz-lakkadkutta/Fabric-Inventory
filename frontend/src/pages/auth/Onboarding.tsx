import { ArrowLeft, ArrowRight, Check, Mail } from 'lucide-react';
import * as React from 'react';
import { useNavigate } from 'react-router-dom';

import { WeaveBg } from '@/components/ui/weave-bg';
import { Wordmark } from '@/components/ui/wordmark';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

/*
  Onboarding — visual port of fabric-2/project/shell-screens.jsx ::
  OnbOrg / OnbFirm / OnbOpening. Three-step wizard with a Stepper header
  and Back / Next / Commit & finish footer. The state machine lives in
  the page and tests verify the behaviour through the heading + footer.
  Real org/firm provisioning wires in TASK-007.
*/
type Step = 0 | 1 | 2;

interface FormData {
  orgName: string;
  contactEmail: string;
  phone: string;
  firmName: string;
  taxRegime: 'gst' | 'non-gst';
  gstin: string;
  pan: string;
  importMode: 'new' | 'vyapar' | 'manual';
}

const INITIAL: FormData = {
  orgName: 'Rajesh Patel Holdings',
  contactEmail: 'rajesh@rpholdings.in',
  phone: '98250 14728',
  firmName: 'Rajesh Textiles, Surat',
  taxRegime: 'gst',
  gstin: '24ABCDE1234F1Z5',
  pan: 'ABCDE1234F',
  importMode: 'vyapar',
};

export default function Onboarding() {
  const [step, setStep] = React.useState<Step>(0);
  const [data, setData] = React.useState<FormData>(INITIAL);
  const navigate = useNavigate();

  const update = <K extends keyof FormData>(key: K, value: FormData[K]) =>
    setData((d) => ({ ...d, [key]: value }));

  return (
    <div
      className="relative flex min-h-full w-full items-center justify-center overflow-hidden py-10"
      style={{ background: 'var(--bg-canvas)' }}
    >
      <WeaveBg opacity={0.04} />
      <div className="relative z-10 px-4" style={{ width: 760 }}>
        <div className="mb-6 flex justify-center">
          <Wordmark size={28} />
        </div>
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 12,
            padding: 28,
            boxShadow: 'var(--shadow-2)',
          }}
        >
          <Stepper active={step} />
          {step === 0 && <OrgStep data={data} update={update} />}
          {step === 1 && <FirmStep data={data} update={update} />}
          {step === 2 && <OpeningStep data={data} update={update} />}
          <div
            className="mt-6 flex justify-between border-t pt-4"
            style={{ borderColor: 'var(--border-subtle)' }}
          >
            {step === 0 ? (
              <Button variant="ghost" onClick={() => navigate('/login')}>
                Cancel
              </Button>
            ) : (
              <Button
                variant="secondary"
                onClick={() => setStep((s) => Math.max(0, s - 1) as Step)}
              >
                <ArrowLeft size={14} />
                Back
              </Button>
            )}
            {step === 0 && (
              <Button onClick={() => setStep(1)}>
                Next: Add firm
                <ArrowRight size={14} />
              </Button>
            )}
            {step === 1 && (
              <Button onClick={() => setStep(2)}>
                Next: Opening balances
                <ArrowRight size={14} />
              </Button>
            )}
            {step === 2 && <Button onClick={() => navigate('/')}>Commit & finish</Button>}
          </div>
        </div>
      </div>
    </div>
  );
}

interface StepperProps {
  active: Step;
}

function Stepper({ active }: StepperProps) {
  const steps = ['Org', 'Firm', 'Opening balances'];
  return (
    <div className="mb-6 flex items-center">
      {steps.map((label, i) => {
        const done = i < active;
        const here = i === active;
        return (
          <React.Fragment key={label}>
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center justify-center"
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 999,
                  background: done
                    ? 'var(--accent)'
                    : here
                      ? 'var(--bg-surface)'
                      : 'var(--bg-sunken)',
                  border: `1.5px solid ${done || here ? 'var(--accent)' : 'var(--border-default)'}`,
                  color: done ? '#FAFAF7' : here ? 'var(--accent)' : 'var(--text-tertiary)',
                  fontSize: 11,
                  fontWeight: 700,
                }}
              >
                {done ? <Check size={12} color="#FAFAF7" /> : i + 1}
              </span>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: here ? 600 : 500,
                  color: here
                    ? 'var(--text-primary)'
                    : done
                      ? 'var(--text-secondary)'
                      : 'var(--text-tertiary)',
                  whiteSpace: 'nowrap',
                }}
              >
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className="mx-3.5 h-px flex-1"
                style={{
                  background: i < active ? 'var(--accent)' : 'var(--border-default)',
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

interface StepProps {
  data: FormData;
  update: <K extends keyof FormData>(key: K, value: FormData[K]) => void;
}

function OrgStep({ data, update }: StepProps) {
  return (
    <>
      <h2 className="m-0" style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em' }}>
        Tell us about your organisation
      </h2>
      <p className="mb-4 mt-1" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        An org can hold one or more firms. You can add more firms later.
      </p>
      <div className="flex flex-col gap-3.5">
        <Field label="Organisation name" htmlFor="org-name" required>
          <Input
            id="org-name"
            value={data.orgName}
            onChange={(e) => update('orgName', e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Contact email" htmlFor="contact-email" required>
            <Input
              id="contact-email"
              type="email"
              value={data.contactEmail}
              onChange={(e) => update('contactEmail', e.target.value)}
              icon={<Mail size={14} />}
            />
          </Field>
          <Field label="Phone" htmlFor="phone">
            <Input
              id="phone"
              prefix={<span style={{ fontSize: 13 }}>+91</span>}
              value={data.phone}
              onChange={(e) => update('phone', e.target.value)}
            />
          </Field>
        </div>
      </div>
    </>
  );
}

function FirmStep({ data, update }: StepProps) {
  return (
    <>
      <h2 className="m-0" style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em' }}>
        Add your first firm
      </h2>
      <p className="mb-4 mt-1" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        Each firm has its own books and invoice series.
      </p>
      <div className="flex flex-col gap-3.5">
        <Field label="Firm name (display)" htmlFor="firm-name" required>
          <Input
            id="firm-name"
            value={data.firmName}
            onChange={(e) => update('firmName', e.target.value)}
          />
        </Field>
        <Field label="Tax regime" required>
          <div className="flex gap-2">
            <SegOpt
              active={data.taxRegime === 'gst'}
              onClick={() => update('taxRegime', 'gst')}
              label="GST registered"
              sub="Charge & reclaim GST"
            />
            <SegOpt
              active={data.taxRegime === 'non-gst'}
              onClick={() => update('taxRegime', 'non-gst')}
              label="Non-GST"
              sub="Below threshold or composition"
            />
          </div>
        </Field>
        {data.taxRegime === 'gst' && (
          <Field label="GSTIN" htmlFor="gstin" required hint="Auto-validates on blur">
            <Input
              id="gstin"
              value={data.gstin}
              onChange={(e) => update('gstin', e.target.value.toUpperCase())}
            />
          </Field>
        )}
        <Field label="PAN" htmlFor="pan" hint="Optional · used for TDS">
          <Input
            id="pan"
            value={data.pan}
            onChange={(e) => update('pan', e.target.value.toUpperCase())}
          />
        </Field>
      </div>
    </>
  );
}

function OpeningStep({ data, update }: StepProps) {
  const options: Array<{ id: FormData['importMode']; label: string; sub: string }> = [
    { id: 'new', label: "I'm new to the trade", sub: 'Skip — start with empty books.' },
    {
      id: 'vyapar',
      label: 'Import from Vyapar (.vyp)',
      sub: 'We parse parties, ledgers, and stock balances.',
    },
    { id: 'manual', label: 'Manual entry', sub: 'Type opening balances yourself.' },
  ];
  return (
    <>
      <h2 className="m-0" style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em' }}>
        Bring in your opening balances
      </h2>
      <p className="mb-4 mt-1" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        Pick how you'd like to start. You can change this within the first 30 days.
      </p>
      <div className="flex flex-col gap-3">
        {options.map((opt) => (
          <RadioRow
            key={opt.id}
            active={data.importMode === opt.id}
            onClick={() => update('importMode', opt.id)}
            label={opt.label}
            sub={opt.sub}
          />
        ))}
      </div>
    </>
  );
}

interface SegOptProps {
  active: boolean;
  label: string;
  sub: string;
  onClick: () => void;
}

function SegOpt({ active, label, sub, onClick }: SegOptProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex-1 text-left"
      style={{
        padding: 14,
        borderRadius: 8,
        border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border-default)'}`,
        background: active ? 'var(--accent-subtle)' : 'var(--bg-surface)',
      }}
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          style={{
            width: 16,
            height: 16,
            borderRadius: 999,
            border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border-strong)'}`,
            background: active ? 'var(--accent)' : 'transparent',
            boxShadow: active ? 'inset 0 0 0 3px var(--bg-surface)' : 'none',
          }}
        />
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: active ? 'var(--accent)' : 'var(--text-primary)',
          }}
        >
          {label}
        </span>
      </div>
      <div
        className="mt-1"
        style={{ fontSize: 12, color: 'var(--text-tertiary)', paddingLeft: 24 }}
      >
        {sub}
      </div>
    </button>
  );
}

interface RadioRowProps {
  active: boolean;
  label: string;
  sub: string;
  onClick: () => void;
}

function RadioRow({ active, label, sub, onClick }: RadioRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left"
      style={{
        padding: 16,
        borderRadius: 8,
        border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border-default)'}`,
        background: 'var(--bg-surface)',
        boxShadow: active ? '0 0 0 3px var(--accent-subtle)' : 'none',
      }}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          style={{
            width: 18,
            height: 18,
            borderRadius: 999,
            border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border-strong)'}`,
            background: active ? 'var(--accent)' : 'transparent',
            boxShadow: active ? 'inset 0 0 0 3px var(--bg-surface)' : 'none',
            flexShrink: 0,
          }}
        />
        <div className="flex-1">
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: active ? 'var(--accent)' : 'var(--text-primary)',
            }}
          >
            {label}
          </div>
          <div className="mt-0.5" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            {sub}
          </div>
        </div>
      </div>
    </button>
  );
}
