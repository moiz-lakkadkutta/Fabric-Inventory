/*
 * Q8a error envelope decoder + ApiError class.
 *
 * Backend always emits:
 *   { code, title, detail, status, field_errors }
 *
 * The api() wrapper throws an ApiError when status >= 400 so callers
 * can switch on `.code` (per Q8b mapping table).
 */

export type ErrorCode =
  | 'INVALID_CREDENTIALS'
  | 'MFA_REQUIRED'
  | 'MFA_INVALID'
  | 'TOKEN_INVALID'
  | 'PERMISSION_DENIED'
  | 'VALIDATION_ERROR'
  | 'IDEMPOTENCY_KEY_REQUIRED'
  | 'IDEMPOTENCY_KEY_PAYLOAD_MISMATCH'
  | 'INVOICE_STATE_ERROR'
  | 'INVOICE_ALREADY_FINALIZED'
  | 'STOCK_INSUFFICIENT'
  | 'GST_PLACE_OF_SUPPLY_AMBIGUOUS'
  | 'NOT_FOUND'
  | 'UNKNOWN';

export interface Q8aEnvelope {
  code: ErrorCode | string;
  title: string;
  detail: string;
  status: number;
  field_errors: Record<string, string[]>;
  /**
   * Server-assigned UUID v4. Surfaced by the request-context middleware.
   * Optional on the client because legacy responses or non-JSON 502s
   * synthesise an envelope without one.
   */
  request_id?: string;
}

export class ApiError extends Error implements Q8aEnvelope {
  readonly code: ErrorCode | string;
  readonly title: string;
  readonly detail: string;
  readonly status: number;
  readonly field_errors: Record<string, string[]>;
  readonly request_id?: string;

  constructor(envelope: Q8aEnvelope) {
    super(`${envelope.code}: ${envelope.title}`);
    this.name = 'ApiError';
    this.code = envelope.code;
    this.title = envelope.title;
    this.detail = envelope.detail;
    this.status = envelope.status;
    this.field_errors = envelope.field_errors ?? {};
    this.request_id = envelope.request_id;
  }
}

/**
 * Decode a fetch Response body into an ApiError. Falls back to a
 * synthesised UNKNOWN envelope if the body isn't JSON (e.g., a 502
 * from a misconfigured proxy).
 *
 * `request_id` falls back to the `x-request-id` response header, which
 * the request-context middleware always emits — useful when an upstream
 * proxy strips the JSON body but preserves headers.
 */
export async function decodeError(response: Response): Promise<ApiError> {
  const headerRequestId = response.headers.get('x-request-id') ?? undefined;
  let envelope: Q8aEnvelope;
  try {
    const data = (await response.json()) as Partial<Q8aEnvelope>;
    envelope = {
      code: data.code ?? 'UNKNOWN',
      title: data.title ?? 'Unknown error',
      detail: data.detail ?? '',
      status: data.status ?? response.status,
      field_errors: data.field_errors ?? {},
      request_id: data.request_id ?? headerRequestId,
    };
  } catch {
    envelope = {
      code: 'UNKNOWN',
      title: `${response.status} ${response.statusText || 'Error'}`,
      detail: 'The server response was not valid JSON.',
      status: response.status,
      field_errors: {},
      request_id: headerRequestId,
    };
  }
  return new ApiError(envelope);
}
