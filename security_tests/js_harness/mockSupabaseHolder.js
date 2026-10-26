module.exports = {
  get supabase() {
    return global.__TEST_SUPABASE__;
  },
  get isSupabaseConfigured() {
    return global.__TEST_IS_CONFIGURED__;
  },
};
