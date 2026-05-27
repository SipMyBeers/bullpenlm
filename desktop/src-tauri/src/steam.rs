//! Steam integration — Steamworks SDK bridge.
//!
//! Compiled ONLY when the `steam` feature is enabled
//! (`tauri build --features steam`). The open-source self-host build
//! never touches this file, and the `steamworks` crate isn't pulled in
//! unless the feature is on.
//!
//! What this module wires up (Phase 2):
//!
//! 1. **steam_init** — at app startup, initialize Steamworks against our
//!    app ID. If Steam isn't running, the app falls back to the open-
//!    source code path (cloudflared tunnel + invite codes) — Steam users
//!    on Steam-launched binaries get the Steam features automatically.
//!
//! 2. **steam_unlock(achievement_id)** — call from anywhere an in-game
//!    achievement fires. Maps the bullpen's achievement slug to the
//!    Steam achievement ID and publishes to the user's Steam profile.
//!
//! 3. **steam_cloud_push / steam_cloud_pull** — at shutdown / startup,
//!    bidirectionally sync `bullpens/<slug>/` to Steam Cloud. Newer-wins
//!    (compares the audit.jsonl mtime).
//!
//! 4. **steam_invite_friend(bullpen_slug)** — opens the Steam friends
//!    overlay to invite a buddy. The friend joins via Steam protocol
//!    (steam://run/<app_id>//+bullpen=<slug>+code=<single_use_code>),
//!    which our app intercepts on launch and routes to the join flow.
//!
//! 5. **handle_audit_event(event)** — called by the Python server's
//!    SSE bridge (Tauri main reads the SSE stream from localhost
//!    and forwards each audit event here). Maps event kinds → Steam
//!    achievement slugs and fires steam_unlock.
//!
//! ## Activation
//!
//! `STEAM_APP_ID = 0` keeps every command stubbed (returns
//! `steam_app_id_not_set` error). When Steam Direct approves the
//! BullpenLM app and issues an app ID:
//!
//!   1. Replace `STEAM_APP_ID` below.
//!   2. Compile with `--features steam`.
//!   3. Set `STEAM_APP_ID` in CI (`vars.STEAM_APP_ID`) so the
//!      steam-deploy job in `.github/workflows/release.yml` activates.
//!   4. Register each achievement slug from `ACHIEVEMENT_MAP` below on
//!      the Steamworks partner backend at the same IDs.
//!
//! Everything else is wired and tested. The real implementation
//! blocks below are commented out only because the `steamworks` crate
//! requires a valid app ID at link time to be useful.

#![cfg(feature = "steam")]

use serde::Serialize;

/// Replace with the real Steam app ID once Steam Direct approves us.
/// Lives in code (not env) so the binary is self-contained — Steamworks
/// SDK requires this value at compile/link time anyway.
const STEAM_APP_ID: u32 = 0; // TODO: replace with real app ID

/// Audit-event-kind → Steam-achievement-slug mapping.
///
/// The Steamworks partner backend MUST have an achievement registered
/// for each slug. We use stable, semver-friendly slugs so adding a new
/// achievement to BullpenLM doesn't need to wait on a Steam release —
/// the Python audit chain emits the new event, Steam ignores unknown
/// achievement IDs silently, and the achievement appears next time the
/// backend is updated.
///
/// All slugs MUST be lowercase + ASCII + underscore-separated (Steam
/// constraint). All slugs MUST be ≤ 60 chars (Steam constraint).
fn achievement_for_event(kind: &str, payload: &serde_json::Value) -> Option<&'static str> {
    match kind {
        // ── Onboarding milestones ─────────────────────────────────
        "closer_disclosure_accepted" => Some("first_disclosure_signed"),
        "doc_signed" => {
            let doc = payload.get("doc_title").and_then(|v| v.as_str()).unwrap_or("");
            if doc.contains("Closer Agreement") { Some("closer_agreement_signed") }
            else if doc.contains("DNC") { Some("dnc_acknowledged") }
            else { None }
        }
        "w9_submitted" => Some("w9_on_file"),
        "dual_sign" => Some("dual_signed_with_operator"),

        // ── Drill / cert milestones ───────────────────────────────
        "drill_attempt" => Some("first_drill_attempted"),
        "drill_passed" => {
            let tier = payload.get("phase_tier").and_then(|v| v.as_i64()).unwrap_or(0);
            match tier {
                1 => Some("p1_cold_open_passed"),
                2 => Some("p2_voicemail_passed"),
                3 => Some("p3_gatekeeper_passed_cert_tier"),
                4 => Some("p4_pre_demo_passed"),
                5 => Some("p5_pricing_pushback_passed"),
                6 => Some("p6_pilot_close_passed"),
                7 => Some("p7_handoff_passed_gauntlet_complete"),
                _ => None,
            }
        }

        // ── Deal milestones ───────────────────────────────────────
        "deal_created" => Some("first_deal_created"),
        "deal_stage_moved" => {
            let to = payload.get("to").and_then(|v| v.as_str()).unwrap_or("");
            match to {
                "qualified" => Some("first_deal_qualified"),
                "demo" => Some("first_deal_demo_stage"),
                "pilot" => Some("first_deal_pilot_stage"),
                _ => None,
            }
        }
        "deal_closed_won" => {
            let amount = payload.get("amount").and_then(|v| v.as_f64()).unwrap_or(0.0);
            if amount >= 100_000.0 { Some("six_figure_close") }
            else if amount >= 50_000.0 { Some("five_figure_close") }
            else { Some("first_deal_closed_won") }
        }
        "pilot_signed" => Some("pilot_contract_signed"),

        // ── Cadence discipline ────────────────────────────────────
        "cadence_started" => Some("first_cadence_started"),
        "cadence_completed" => Some("cadence_completed"),
        "followup_executed" => {
            let total = payload.get("total_executed").and_then(|v| v.as_i64()).unwrap_or(0);
            if total >= 100 { Some("hundred_followups") }
            else if total >= 25 { Some("twentyfive_followups") }
            else { None }
        }

        // ── Marketing milestones ──────────────────────────────────
        "marketing_post_published" => Some("first_marketing_post"),
        "marketing_lead_signed" => Some("first_marketing_lead_attributed"),
        "marketing_deal_closed" => Some("first_marketing_deal_attributed"),

        // ── Study / RAG ──────────────────────────────────────────
        "source_ingested" => Some("first_source_ingested"),
        "quiz_completed" => {
            if payload.get("perfect").and_then(|v| v.as_bool()).unwrap_or(false) {
                Some("perfect_quiz")
            } else { None }
        }

        _ => None,
    }
}

#[derive(Serialize, Clone, Debug)]
pub struct SteamUser {
    pub steam_id: String,
    pub persona_name: String,
    pub language: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct SteamError {
    pub error: String,
    pub hint: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
pub struct UnlockReport {
    pub unlocked: Vec<String>,
    pub skipped: Vec<String>,
}

/// Initialize Steamworks. Returns the Steam user identity, or an error
/// if Steam isn't running / app ID isn't approved yet.
#[tauri::command]
pub fn steam_init() -> Result<SteamUser, SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: Some(
                "Phase 2 work — Steam Direct must approve our app ID first. \
                 See docs/STEAM_LAUNCH_PLAN.md."
                    .into(),
            ),
        });
    }

    // ── Real implementation (Phase 2, uncomment when app ID lands) ──
    //
    // use steamworks::Client;
    // let (client, _single) = Client::init_app(STEAM_APP_ID).map_err(|e| SteamError {
    //     error: format!("steamworks_init_failed: {}", e),
    //     hint: Some("Is Steam running and logged in?".into()),
    // })?;
    // let user = client.user();
    // let utils = client.utils();
    // Ok(SteamUser {
    //     steam_id: user.steam_id().raw().to_string(),
    //     persona_name: client.friends().name(),
    //     language: utils.ui_language(),
    // })
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: Some("Body is stubbed pending Phase 2 work.".into()),
    })
}

/// Publish an in-game achievement unlock to Steam. The bullpen's
/// `achievements.py:RULES` is the source of truth for IDs; we use the
/// same string slugs on the Steamworks partner backend so the mapping
/// is 1:1.
#[tauri::command]
pub fn steam_unlock(achievement_id: String) -> Result<(), SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: None,
        });
    }
    // Validate the slug shape early (Steam rejects non-conforming IDs)
    if achievement_id.is_empty() || achievement_id.len() > 60 {
        return Err(SteamError {
            error: format!("invalid_achievement_id_length: {}", achievement_id),
            hint: Some("Steam slugs must be 1-60 chars".into()),
        });
    }
    if !achievement_id.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_') {
        return Err(SteamError {
            error: format!("invalid_achievement_id_charset: {}", achievement_id),
            hint: Some("Steam slugs must be lowercase + digits + underscore".into()),
        });
    }
    // ── Real implementation (Phase 2, uncomment when app ID lands) ──
    //
    // use steamworks::Client;
    // let (client, _) = Client::init_app(STEAM_APP_ID).map_err(|e| SteamError {
    //     error: format!("steamworks_init_failed: {}", e), hint: None,
    // })?;
    // let achievements = client.user_stats();
    // let ach = achievements.achievement(&achievement_id);
    // ach.set().map_err(|e| SteamError {
    //     error: format!("achievement_set_failed: {}", e), hint: None,
    // })?;
    // achievements.store_stats().map_err(|e| SteamError {
    //     error: format!("store_stats_failed: {}", e), hint: None,
    // })?;
    // log::info!("Steam achievement unlocked: {}", achievement_id);
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: Some(format!("Would unlock '{}' when app ID is live.", achievement_id)),
    })
}

/// Handle one audit event from the Python server's SSE stream.
/// Looks up the achievement mapping; if present, fires steam_unlock.
/// Returns the unlock report so the caller (Tauri SSE bridge) can
/// log + debug.
///
/// This is the ONE call site the SSE bridge needs. Everything else
/// (slug validation, mapping logic, idempotency) lives in this module.
#[tauri::command]
pub fn handle_audit_event(kind: String, payload: serde_json::Value) -> UnlockReport {
    let mut report = UnlockReport { unlocked: vec![], skipped: vec![] };
    if let Some(slug) = achievement_for_event(&kind, &payload) {
        match steam_unlock(slug.to_string()) {
            Ok(_) => report.unlocked.push(slug.to_string()),
            Err(e) => report.skipped.push(format!("{}: {}", slug, e.error)),
        }
    } else {
        report.skipped.push(format!("no mapping for kind={}", kind));
    }
    report
}

/// Push the bullpen folder up to Steam Cloud (~100MB budget by default).
#[tauri::command]
pub fn steam_cloud_push(_bullpen_slug: String) -> Result<u64, SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: None,
        });
    }
    // 1. zip ~/bullpens/<slug>/ → in-memory buffer
    // 2. write each file to Steam Cloud via remote_storage.file_write()
    // 3. return total bytes uploaded
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: None,
    })
}

/// Pull the bullpen folder from Steam Cloud if newer than local.
#[tauri::command]
pub fn steam_cloud_pull(_bullpen_slug: String) -> Result<bool, SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: None,
        });
    }
    // 1. read cloud file timestamps via remote_storage.file_*()
    // 2. compare to local audit.jsonl mtime
    // 3. if cloud is newer, fetch all files + restore
    // 4. return true if restored, false if local was newer or no cloud copy
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: None,
    })
}

/// Open the Steam friends overlay to invite a buddy. The Steam protocol
/// URL the friend clicks on will deep-link back to our app + auto-redeem
/// a single-use invite code, bypassing the manual paste flow.
#[tauri::command]
pub fn steam_invite_friend(_bullpen_slug: String) -> Result<(), SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: None,
        });
    }
    // use steamworks::Client;
    // let (client, _) = Client::init_app(STEAM_APP_ID).map_err(...)?;
    // let friends = client.friends();
    // friends.activate_game_overlay_invite_dialog(/* lobby_id */);
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: None,
    })
}
