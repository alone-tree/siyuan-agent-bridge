export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // POST /api/telemetry — 遥测事件写入
    if (path === '/api/telemetry' && request.method === 'POST') {
      try {
        const body = await request.json();
        const events = Array.isArray(body) ? body : [body];

        const stmt = env.DB.prepare(
          `INSERT INTO events (ts, anonymous_id, platform, siyuan_ver, mcp_ver, session_id, tool, action, ok, error_type, dur_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        );

        const batch = events.map(e =>
          stmt.bind(
            e.ts, e.anonymous_id, e.platform || null, e.siyuan_ver || null,
            e.mcp_ver || null, e.session_id || null, e.tool, e.action || null,
            e.ok ? 1 : 0, e.error_type || null, e.dur_ms || null
          )
        );

        await env.DB.batch(batch);
        return new Response(JSON.stringify({ ok: true, count: events.length }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: 'invalid payload' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // POST /api/feedback — 用户反馈写入
    if (path === '/api/feedback' && request.method === 'POST') {
      try {
        const body = await request.json();
        if (!body.type || !body.title || !body.description) {
          return new Response(JSON.stringify({ ok: false, error: 'missing required fields' }), {
            status: 400,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        await env.DB.prepare(
          `INSERT INTO feedbacks (ts, type, title, description, contact)
           VALUES (?, ?, ?, ?, ?)`
        ).bind(
          new Date().toISOString(), body.type, body.title, body.description, body.contact || null
        ).run();

        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: 'invalid payload' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // GET /api/notifications — 通知列表
    if (path === '/api/notifications' && request.method === 'GET') {
      try {
        const { results } = await env.DB.prepare(
          `SELECT id, title, url FROM notifications ORDER BY created_at DESC`
        ).all();

        return new Response(JSON.stringify({ notifications: results }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      } catch (e) {
        return new Response(JSON.stringify({ notifications: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // 404
    return new Response('Not Found', { status: 404 });
  }
};
