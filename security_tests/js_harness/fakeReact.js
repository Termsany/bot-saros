// Minimal synchronous React hook shim used ONLY to exercise app/auth/page.tsx's
// logic in isolation for the recovery-mode security regression test.
// It intentionally mimics React's "stale closure per render" semantics: state
// read inside a render is a snapshot; effects/callbacks mutate a shared store
// and the caller must invoke render() again to observe the new value, exactly
// like a real React re-render would.

let store = [];
let cursor = 0;
let effects = [];

function useState(initial) {
  const i = cursor++;
  if (store.length <= i) {
    store.push(typeof initial === "function" ? initial() : initial);
  }
  const index = i;
  const setter = (value) => {
    store[index] = typeof value === "function" ? value(store[index]) : value;
  };
  return [store[index], setter];
}

function useEffect(fn, _deps) {
  effects.push(fn);
}

function runPendingEffects() {
  const pending = effects;
  effects = [];
  pending.forEach((fn) => fn());
}

function beginRender() {
  cursor = 0;
}

function resetAll() {
  store = [];
  cursor = 0;
  effects = [];
}

module.exports = { useState, useEffect, runPendingEffects, beginRender, resetAll };
