import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  validateExecutionEvent, canonicalJson, toCloudEvent, fromCloudEvent, toOtelTraceContext,
} from '../execution_v1_interop.mjs';

const fixtures = JSON.parse(readFileSync(
  new URL('../../fixtures/execution_v1/interop_cases.json', import.meta.url), 'utf8'));
assert.equal(fixtures.profile, 'acp.execution.v1.interop-fixtures.v1');
const cases = new Map(fixtures.cases.map(f => [f.name, f]));
function mutate(obj, mutation) {
  const clone = structuredClone(obj);
  const path = mutation.path;
  let target = clone;
  for (const key of path.slice(0, -1)) target = target[key];
  if (mutation.remove) delete target[path.at(-1)];
  else target[path.at(-1)] = mutation.value;
  return clone;
}

for (const fixture of fixtures.cases) {
  test('Node.js golden event and CloudEvents: ' + fixture.name, () => {
    const event = validateExecutionEvent(fixture.event);
    const envelope = toCloudEvent(event);
    assert.equal(envelope.id, fixture.expected.cloudevent_id);
    assert.equal(envelope.source, fixture.expected.cloudevent_source);
    assert.equal(envelope.specversion, '1.0');
    assert.equal(envelope.type, 'org.ndrorchestration.acp.execution.v1');
    assert.deepEqual(fromCloudEvent(JSON.parse(JSON.stringify(envelope))), event);
    assert.equal(canonicalJson(toCloudEvent(event)), canonicalJson(envelope));
    if (fixture.expected.otel === null) {
      assert.throws(() => toOtelTraceContext(event), /invalid OTel/);
    } else {
      assert.deepEqual(toOtelTraceContext(event), fixture.expected.otel);
    }
  });
}
for (const mutation of fixtures.mutations) {
  test('Node.js shared fail-closed mutation: ' + mutation.name, () => {
    const original = cases.get(mutation.case).event;
    if (mutation.target === 'envelope') {
      assert.throws(() => fromCloudEvent(mutate(toCloudEvent(original), mutation)), TypeError);
    } else {
      assert.throws(() => validateExecutionEvent(mutate(original, mutation)), TypeError);
    }
  });
}
test('Node.js never grants authority from syntactic success', () => {
  const denied = cases.get('denied-uri-escaping').event;
  const cloudEvent = toCloudEvent(denied);
  assert.equal(cloudEvent.data.status, 'denied');
  assert.equal(cloudEvent.data.policy_decision_ref, 'explicit-deny-18');
  assert.ok(!Object.hasOwn(cloudEvent, 'authorized'));
});
