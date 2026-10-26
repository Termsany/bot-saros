// Behavioral regression harness for app/auth/page.tsx recovery-mode gating.
//
// It transpiles the real page.tsx source (only swapping unresolvable module
// aliases for local mocks and adding a test-only state-exposure hook; the
// component's own logic/effects/submit() are untouched) and executes
// AuthPage() against a fake synchronous React + mocked Supabase client, so
// we exercise the ACTUAL effect/submit code paths rather than
// re-implementing them. app/auth/page.tsx on disk is never modified by this
// harness; only an in-memory copy is transpiled and run.
//
// Scenarios:
//  1. Spoofed URL only ("?type=recovery" / "#type=recovery", no real auth
//     event) must NOT put the component into recovery mode, and submit()
//     must never call supabase.auth.updateUser.
//  2. A genuine PASSWORD_RECOVERY onAuthStateChange event MUST put the
//     component into recovery mode, and submit() in that verified state
//     must call supabase.auth.updateUser exactly once with the new password.

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const ts = require("typescript");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const PAGE_PATH = path.join(REPO_ROOT, "app", "auth", "page.tsx");

function loadTransformedSource() {
  const raw = fs.readFileSync(PAGE_PATH, "utf8");

  const importBlockPattern =
    /import\s*\{\s*useEffect,\s*useState\s*\}\s*from\s*"react"[\s\S]*?import\s*\{\s*supabase,\s*isSupabaseConfigured\s*\}\s*from\s*"@\/lib\/supabase"\s*\r?\n/;
  if (!importBlockPattern.test(raw)) {
    throw new Error(
      "harness could not locate the expected import block in app/auth/page.tsx; " +
        "update security_tests/js_harness/compileAndRunRecoveryHarness.js"
    );
  }
  const mockImports = [
    'const { useEffect, useState } = require("./fakeReact");',
    'const BRAND = { name: "RAQM", nameAr: "\u0631\u0642\u0645" };',
    "function Logo() { return null; }",
    'const { supabase, isSupabaseConfigured } = require("./mockSupabaseHolder");',
    "",
  ].join("\n");
  let out = raw.replace(importBlockPattern, mockImports);

  const titleAnchor = 'const title = mode === "login"';
  if (!out.includes(titleAnchor)) {
    throw new Error(
      "harness could not locate the render anchor in app/auth/page.tsx; " +
        "update security_tests/js_harness/compileAndRunRecoveryHarness.js"
    );
  }
  const exposeHook =
    'if (typeof global !== "undefined" && global.__TEST_EXPOSE__) {\n' +
    "  global.__TEST_EXPOSE__({ mode, setMode, newPassword, setNewPassword, confirmPassword, setConfirmPassword, submit, msg });\n" +
    "}\n";
  out = out.replace(titleAnchor, exposeHook + titleAnchor);

  return out;
}

function compileToCommonJs(source) {
  const result = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2019,
      esModuleInterop: true,
    },
    fileName: "page.tsx",
  });
  return result.outputText;
}

function writeCompiledModule(jsSource) {
  const tmpFile = path.join(
    __dirname,
    `_compiled_page.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2)}.generated.js`
  );
  fs.writeFileSync(tmpFile, jsSource, "utf8");
  return tmpFile;
}

function setupWindowAndDocument(search, hash) {
  global.window = {
    location: {
      search: search || "",
      hash: hash || "",
      origin: "https://app.example.com",
      assign() {},
    },
    history: { replaceState() {} },
    setTimeout: (fn) => fn(),
  };
  global.document = { title: "RAQM" };
}

function runScenario({ search, hash, fireRecoveryEvent }) {
  delete require.cache[require.resolve("./fakeReact")];
  const fakeReact = require("./fakeReact");
  fakeReact.resetAll();

  setupWindowAndDocument(search, hash);

  delete require.cache[require.resolve("./mockSupabase")];
  const { createMockSupabase } = require("./mockSupabase");
  const { supabase, isSupabaseConfigured, calls, fireAuthEvent } = createMockSupabase();
  global.__TEST_SUPABASE__ = supabase;
  global.__TEST_IS_CONFIGURED__ = isSupabaseConfigured;

  const compiledPath = writeCompiledModule(compileToCommonJs(loadTransformedSource()));
  let AuthPage;
  try {
    delete require.cache[require.resolve("./mockSupabaseHolder")];
    delete require.cache[compiledPath];
    const pageModule = require(compiledPath);
    AuthPage = pageModule.default;
  } finally {
    fs.unlinkSync(compiledPath);
  }

  let snapshot = null;
  global.__TEST_EXPOSE__ = (internals) => {
    snapshot = internals;
  };

  // Initial render (mount) + effect flush, mirroring React's commit phase.
  fakeReact.beginRender();
  AuthPage();
  fakeReact.runPendingEffects();

  if (fireRecoveryEvent) {
    fireAuthEvent("PASSWORD_RECOVERY");
  }

  // Re-render to observe any state updates made by the effect / event.
  fakeReact.beginRender();
  AuthPage();

  delete global.__TEST_EXPOSE__;

  function rerender() {
    global.__TEST_EXPOSE__ = (internals) => {
      snapshot = internals;
    };
    fakeReact.beginRender();
    AuthPage();
    delete global.__TEST_EXPOSE__;
  }

  const result = { calls, rerender };
  Object.defineProperty(result, "snapshot", { get: () => snapshot });
  return result;
}

async function main() {
  const failures = [];

  async function check(label, fn) {
    try {
      await fn();
      console.log(`PASS: ${label}`);
    } catch (err) {
      failures.push(label);
      console.log(`FAIL: ${label} -> ${err.message}`);
    }
  }

  // Scenario 1: spoofed query string alone, no genuine auth event.
  const spoofedQuery = runScenario({ search: "?type=recovery", fireRecoveryEvent: false });
  await check(
    "spoofed ?type=recovery query string alone does not enter recovery mode",
    () => assert.strictEqual(spoofedQuery.snapshot.mode, "login")
  );
  await check("spoofed query string: submit() never calls updateUser", async () => {
    spoofedQuery.snapshot.setNewPassword("Attacker#12345");
    spoofedQuery.snapshot.setConfirmPassword("Attacker#12345");
    spoofedQuery.rerender();
    await spoofedQuery.snapshot.submit();
    assert.strictEqual(spoofedQuery.calls.updateUserCalls.length, 0);
  });

  // Scenario 1b: spoofed recovery hash alone, no genuine auth event.
  const spoofedHash = runScenario({ hash: "#type=recovery", fireRecoveryEvent: false });
  await check(
    "spoofed #type=recovery hash alone does not enter recovery mode",
    () => assert.strictEqual(spoofedHash.snapshot.mode, "login")
  );

  // Scenario 2: genuine PASSWORD_RECOVERY event fires -> recovery mode, and
  // submit() in that verified state calls updateUser exactly once.
  const genuine = runScenario({ fireRecoveryEvent: true });
  await check("genuine PASSWORD_RECOVERY event enters recovery mode", () =>
    assert.strictEqual(genuine.snapshot.mode, "recovery")
  );
  await check("genuine recovery mode: submit() calls updateUser exactly once", async () => {
    genuine.snapshot.setNewPassword("NewStrongPass#1");
    genuine.snapshot.setConfirmPassword("NewStrongPass#1");
    genuine.rerender();
    await genuine.snapshot.submit();
    assert.strictEqual(genuine.calls.updateUserCalls.length, 1);
    assert.deepStrictEqual(genuine.calls.updateUserCalls[0], { password: "NewStrongPass#1" });
  });

  if (failures.length > 0) {
    console.log(`\n${failures.length} scenario(s) failed.`);
    process.exitCode = 1;
  } else {
    console.log("\nAll recovery-mode behavioral scenarios passed.");
    process.exitCode = 0;
  }
}

main();
