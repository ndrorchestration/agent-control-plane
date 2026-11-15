/**
 * Cross-process Python <-> Node.js tests: two independently launched language
 * runtimes exchange synthetic JSON CloudEvents over bounded stdio, no network.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { toCloudEvent } from '../execution_v1_interop.mjs';

const corpus = JSON.parse(readFileSync(
  new URL('../../fixtures/execution_v1/interop_cases.json', import.meta.url), 'utf8'));
const cases = new Map(corpus.cases.map(c => [c.name, c]));

const python = process.env.PYTHON || 'python';
const tools = {
  python: [python, ['-m', 'integration.execution_v1_bridge']],
  node: [process.execPath, ['integration/execution_v1_bridge.mjs']],
};

function call(runtime, request, expectedSuccess = true) {
  const [command, args] = tools[runtime];
  const input = typeof request === 'string' ? request : JSON.stringify(request);
  const output = spawnSync(command, args, {
    input, encoding: 'utf8', timeout: 10000, maxBuffer: 1024 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(output.error, undefined, runtime + ' launch failed');
  if (expectedSuccess) {
    assert.equal(output.status, 0, runtime + ' rejected valid interchange: ' + output.stderr);
    assert.equal(output.stderr, '');
    return JSON.parse(output.stdout);
  }
  assert.equal(output.status, 2, runtime + ' did not fail closed: ' + output.stderr);
  assert.equal(output.stdout, '', runtime + ' emitted untrusted output');
  assert.equal(output.stderr.trim(), 'ACP_INTEROP_REJECTED');
  return undefined;
}
function altered(value, instruction) {
  const next = structuredClone(value);
  let target = next;
  for (const key of instruction.path.slice(0, -1)) target = target[key];
  const last = instruction.path.at(-1);
  if (instruction.remove === true) delete target[last];
  else target[last] = instruction.value;
  return next;
}

for (const f of corpus.cases) {
  test('Python encodes -> Node decodes: ' + f.name, () => {
    const envelope = call('python', { operation: 'encode', payload: f.event });
    assert.equal(envelope.id, f.expected.cloudevent_id);
    assert.equal(envelope.source, f.expected.cloudevent_source);
    const event = call('node', { operation: 'decode', payload: envelope });
    assert.deepEqual(event, f.event);
    assert.equal(event.status, f.event.status);
    assert.equal(event.policy_decision_ref, f.event.policy_decision_ref);
  });
  test('Node encodes -> Python decodes: ' + f.name, () => {
    const envelope = call('node', { operation: 'encode', payload: f.event });
    assert.equal(envelope.id, f.expected.cloudevent_id);
    const event = call('python', { operation: 'decode', payload: envelope });
    assert.deepEqual(event, f.event);
    assert.equal(event.status, f.event.status);
    assert.equal(event.policy_decision_ref, f.event.policy_decision_ref);
  });
}

for (const instruction of corpus.mutations) {
  test('Cross-process reject in both runtimes: ' + instruction.name, () => {
    const original = cases.get(instruction.case).event;
    const envelope = toCloudEvent(original);
    const input = instruction.target === 'event'
      ? { operation: 'encode', payload: altered(original, instruction) }
      : { operation: 'decode', payload: altered(envelope, instruction) };
    call('python', input, false);
    call('node', input, false);
  });
}

for (const runtime of ['python', 'node']) {
  test(runtime + ' rejects unauthorized operation', () => {
    call(runtime, { operation: 'authorize', payload: cases.get('completed-unicode-artifacts').event }, false);
  });
  test(runtime + ' rejects extra request controls', () => {
    call(runtime, { operation: 'encode', payload: cases.get('completed-unicode-artifacts').event, authorized: true }, false);
  });
  test(runtime + ' rejects invalid and oversized input', () => {
    call(runtime, '{"operation":', false);
    call(runtime, 'x'.repeat(65537), false);
  });
}
