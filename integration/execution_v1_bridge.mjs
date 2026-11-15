/**
 * Non-authorizing, bounded JSON-over-stdio interchange facade for Node.js.
 * Invocation: node integration/execution_v1_bridge.mjs
 * Neither encode nor decode performs tasks, authorizes tools, or contacts peers.
 */
import { toCloudEvent, fromCloudEvent, validateExecutionEvent } from './execution_v1_interop.mjs';

const MAX_BYTES = 65536;
function reject() {
  process.stderr.write('ACP_INTEROP_REJECTED\n');
  process.exitCode = 2;
}
function exactRequest(value) {
  if (value === null || Array.isArray(value) || typeof value !== 'object' ||
      Object.keys(value).length !== 2 || !Object.hasOwn(value, 'operation') ||
      !Object.hasOwn(value, 'payload')) throw new TypeError('invalid request');
  if (value.operation !== 'encode' && value.operation !== 'decode') {
    throw new TypeError('unsupported operation');
  }
}
try {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > MAX_BYTES) throw new TypeError('bounded input exceeded');
    chunks.push(chunk);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  exactRequest(request);
  const result = request.operation === 'encode'
    ? toCloudEvent(validateExecutionEvent(request.payload))
    : fromCloudEvent(request.payload);
  process.stdout.write(JSON.stringify(result) + '\n');
} catch {
  reject();
}
