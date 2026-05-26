/**
 * BullpenLM email Worker.
 *
 * One Worker per Beers Labs Cloudflare account. Beers's primary host calls
 * this Worker over HTTPS with a shared secret; the Worker sends the email
 * via the `send_email` binding from a brand-verified domain.
 *
 * Bullpen hosts that want their own branded sending will deploy their own
 * copy of this Worker against their own Cloudflare account + domain. The
 * BullpenLM repo ships this scaffold so they can `wrangler deploy` and be
 * live in a few minutes (see README.md).
 *
 * The Worker is intentionally thin:
 *   - Authn via shared secret in `Authorization: Bearer <secret>`
 *   - Validates the `from` domain matches an allow-list (defined in env)
 *   - Sends via env.EMAIL.send() and returns the result
 *
 * Template rendering lives in the BullpenLM host (server/email_templates.py).
 * This Worker is the last mile to Cloudflare's email infra.
 */

import { Hono } from "hono";

interface Env {
  EMAIL: SendEmail;
  BULLPENLM_SHARED_SECRET: string;
  ALLOWED_FROM_DOMAINS?: string;
  DEFAULT_REPLY_TO?: string;
}

interface SendBody {
  from: { email: string; name?: string };
  to: string | string[];
  subject: string;
  html: string;
  text: string;
  reply_to?: string;
  cc?: string | string[];
  bcc?: string | string[];
}

const app = new Hono<{ Bindings: Env }>();

// ── Auth middleware ─────────────────────────────────────────────────────
app.use("/send/*", async (c, next) => {
  const auth = c.req.header("Authorization") || "";
  const expected = `Bearer ${c.env.BULLPENLM_SHARED_SECRET || ""}`;
  if (!c.env.BULLPENLM_SHARED_SECRET || auth !== expected) {
    return c.json({ error: "unauthorized" }, 401);
  }
  await next();
});

// ── Health ──────────────────────────────────────────────────────────────
app.get("/", (c) => c.json({ ok: true, service: "bullpenlm-email", v: "0.1" }));

// ── POST /send — single transactional email ─────────────────────────────
app.post("/send", async (c) => {
  let body: SendBody;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid_json" }, 400);
  }

  if (!body.from?.email || !body.to || !body.subject || !(body.html || body.text)) {
    return c.json({ error: "missing_required_fields",
                    required: ["from.email", "to", "subject", "html_or_text"] }, 400);
  }

  // Optional from-domain allow-list (comma-separated, env var).
  const allowed = (c.env.ALLOWED_FROM_DOMAINS || "")
    .split(",").map((s) => s.trim()).filter(Boolean);
  if (allowed.length) {
    const fromDomain = body.from.email.split("@").pop() || "";
    if (!allowed.includes(fromDomain)) {
      return c.json({
        error: "from_domain_not_allowed",
        from_domain: fromDomain,
        allowed,
      }, 403);
    }
  }

  try {
    const response = await c.env.EMAIL.send({
      to: body.to,
      from: { email: body.from.email, name: body.from.name },
      subject: body.subject,
      html: body.html || undefined,
      text: body.text || undefined,
      replyTo: body.reply_to || c.env.DEFAULT_REPLY_TO || undefined,
      cc: body.cc,
      bcc: body.bcc,
    });
    return c.json({ ok: true, messageId: response?.messageId, response });
  } catch (e) {
    return c.json({
      error: "send_failed",
      detail: e instanceof Error ? e.message : String(e),
    }, 502);
  }
});

export default app;
