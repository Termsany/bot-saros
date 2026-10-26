// Mock @/lib/supabase for the recovery-mode behavior harness.
// A fresh object is produced per test scenario via createMockSupabase().

function createMockSupabase() {
  const calls = {
    onAuthStateChangeCallbacks: [],
    updateUserCalls: [],
    getSessionCalls: 0,
  };

  const supabase = {
    auth: {
      onAuthStateChange(cb) {
        calls.onAuthStateChangeCallbacks.push(cb);
        return { data: { subscription: { unsubscribe() {} } } };
      },
      async updateUser(payload) {
        calls.updateUserCalls.push(payload);
        return { data: {}, error: null };
      },
      async getSession() {
        calls.getSessionCalls += 1;
        return { data: { session: null }, error: null };
      },
      async signInWithPassword() {
        return { data: {}, error: null };
      },
      async signUp() {
        return { data: {}, error: null };
      },
      async resetPasswordForEmail() {
        return { data: {}, error: null };
      },
    },
  };

  function fireAuthEvent(event) {
    calls.onAuthStateChangeCallbacks.forEach((cb) => cb(event));
  }

  return { supabase, isSupabaseConfigured: true, calls, fireAuthEvent };
}

module.exports = { createMockSupabase };
