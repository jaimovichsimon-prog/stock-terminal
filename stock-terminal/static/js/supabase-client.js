// ---------------------------------------------------------------------------
// Supabase singleton client. Loaded after the SDK and before app.js.
// SUPABASE_URL and SUPABASE_ANON_KEY are injected by FastAPI into window.*
// ---------------------------------------------------------------------------
(function () {
  if (!window.supabase || typeof window.supabase.createClient !== 'function') {
    console.error('Supabase SDK not loaded before supabase-client.js');
    return;
  }
  if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
    console.error('SUPABASE_URL / SUPABASE_ANON_KEY not injected by server');
    return;
  }
  window.sbClient = window.supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
})();
