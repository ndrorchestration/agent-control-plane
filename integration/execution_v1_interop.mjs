/**
 * Read-only, non-authorizing ACP execution.v1 interoperability profile.
 * This stand-alone Node.js implementation consumes the same golden vectors
 * as Python. Successful parsing or a matching digest does not grant authority.
 */
import { createHash } from 'node:crypto';

const EVENT_KEYS = ['event_type', 'identity', 'trace', 'component', 'task_id',
  'status', 'utc_timestamp', 'monotonic_ns', 'capability', 'policy_decision_ref',
  'input_artifacts', 'output_artifacts', 'detail'];
const IDENTITY_KEYS = ['execution_id', 'run_id', 'schema_version'];
const TRACE_KEYS = ['trace_id', 'span_id', 'parent_span_id'];
const COMPONENT_KEYS = ['component_id', 'component_type', 'runtime_id',
  'adapter_id', 'version', 'source_ref'];
const ARTIFACT_KEYS = ['artifact_id', 'kind', 'uri', 'version', 'sha256'];
const ENVELOPE_KEYS = ['specversion', 'id', 'source', 'type', 'subject', 'time',
  'datacontenttype', 'data'];
const TRACE_HEX = /^[0-9a-f]{32}$/;
const SPAN_HEX = /^[0-9a-f]{16}$/;

function invalid(message) { throw new TypeError('ACP interop: ' + message); }
function record(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}
function exactFields(value, fields, name) {
  if (!record(value) || Object.keys(value).length !== fields.length ||
      fields.some(k => !Object.hasOwn(value, k))) invalid(name + ' fields mismatch');
}
function requiredString(value, name) {
  if (typeof value !== 'string' || !value.trim()) invalid(name + ' required');
}
function nullableString(value, name) {
  if (value !== null) requiredString(value, name);
}
function artifact(value) {
  exactFields(value, ARTIFACT_KEYS, 'artifact');
  requiredString(value.artifact_id, 'artifact_id');
  requiredString(value.kind, 'kind');
  nullableString(value.uri, 'artifact.uri');
  nullableString(value.version, 'artifact.version');
  if (value.sha256 !== null && (typeof value.sha256 !== 'string' ||
      !/^[0-9a-f]{64}$/.test(value.sha256))) invalid('artifact.sha256 malformed');
}
function validUtc(value) {
  if (typeof value !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$/.test(value)) {
    invalid('utc_timestamp must be canonical UTC');
  }
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime()) ||
      parsed.toISOString().slice(0, 19) !== value.slice(0, 19) ||
      Number(value.slice(0, 4)) === 0) invalid('utc_timestamp invalid calendar time');
}

/** Strict portable subset: safe numeric integers, canonical UTC, exact fields. */
export function validateExecutionEvent(value) {
  exactFields(value, EVENT_KEYS, 'execution event');
  requiredString(value.event_type, 'event_type');
  requiredString(value.task_id, 'task_id');
  requiredString(value.status, 'status');
  validUtc(value.utc_timestamp);
  if (!Number.isSafeInteger(value.monotonic_ns) || value.monotonic_ns < 0) {
    invalid('monotonic_ns must be a nonnegative safe integer');
  }
  nullableString(value.capability, 'capability');
  nullableString(value.policy_decision_ref, 'policy_decision_ref');
  nullableString(value.detail, 'detail');
  exactFields(value.identity, IDENTITY_KEYS, 'identity');
  requiredString(value.identity.execution_id, 'execution_id');
  requiredString(value.identity.run_id, 'run_id');
  if (value.identity.schema_version !== 'agent-control-plane.execution.v1') {
    invalid('unsupported execution schema version');
  }
  exactFields(value.trace, TRACE_KEYS, 'trace');
  requiredString(value.trace.trace_id, 'trace_id');
  requiredString(value.trace.span_id, 'span_id');
  nullableString(value.trace.parent_span_id, 'parent_span_id');
  if (value.trace.parent_span_id === value.trace.span_id) invalid('self-parenting span');
  exactFields(value.component, COMPONENT_KEYS, 'component');
  for (const key of ['component_id', 'component_type', 'runtime_id', 'adapter_id']) {
    requiredString(value.component[key], key);
  }
  nullableString(value.component.version, 'version');
  nullableString(value.component.source_ref, 'source_ref');
  for (const key of ['input_artifacts', 'output_artifacts']) {
    if (!Array.isArray(value[key])) invalid(key + ' must be array');
    value[key].forEach(artifact);
  }
  return value;
}

/** Stable JSON bytes for the bounded execution.v1 model (ASCII field names). */
export function canonicalJson(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) invalid('numbers must be safe integers');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (!record(value)) invalid('unsupported JSON value');
  return '{' + Object.keys(value).sort().map(k =>
    JSON.stringify(k) + ':' + canonicalJson(value[k])).join(',') + '}';
}
function pathSegment(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, c =>
    '%' + c.codePointAt(0).toString(16).toUpperCase());
}

export function toCloudEvent(event) {
  validateExecutionEvent(event);
  const digest = createHash('sha256').update(canonicalJson(event), 'utf8').digest('hex');
  return {
    specversion: '1.0', id: digest,
    source: '/agent-control-plane/' + pathSegment(event.component.runtime_id) + '/' +
      pathSegment(event.component.component_id),
    type: 'org.ndrorchestration.acp.execution.v1',
    subject: event.task_id,
    time: event.utc_timestamp,
    datacontenttype: 'application/json',
    data: event,
  };
}

export function fromCloudEvent(envelope) {
  exactFields(envelope, ENVELOPE_KEYS, 'CloudEvents envelope');
  validateExecutionEvent(envelope.data);
  if (canonicalJson(envelope) !== canonicalJson(toCloudEvent(envelope.data))) {
    invalid('CloudEvents envelope does not match execution data');
  }
  return envelope.data;
}

/** Reject legacy/non-OTel IDs; never fabricate or silently upgrade them. */
export function toOtelTraceContext(event) {
  validateExecutionEvent(event);
  const { trace_id, span_id, parent_span_id } = event.trace;
  if (!TRACE_HEX.test(trace_id) || !/[1-9a-f]/.test(trace_id)) invalid('invalid OTel trace_id');
  if (!SPAN_HEX.test(span_id) || !/[1-9a-f]/.test(span_id)) invalid('invalid OTel span_id');
  if (parent_span_id !== null &&
      (!SPAN_HEX.test(parent_span_id) || !/[1-9a-f]/.test(parent_span_id))) {
    invalid('invalid OTel parent_span_id');
  }
  return { trace_id, span_id, parent_span_id };
}
