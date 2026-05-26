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
//! Until our Steam Direct application is approved and we have an app ID,
//! every `#[tauri::command]` below is a stub that returns an error. Once
//! the app ID lands, replace the `STEAM_APP_ID` constant and uncomment
//! the real implementations.

#![cfg(feature = "steam")]

use serde::Serialize;

/// Replace with the real Steam app ID once Steam Direct approves us.
/// Lives in code (not env) so the binary is self-contained — Steamworks
/// SDK requires this value at compile/link time anyway.
const STEAM_APP_ID: u32 = 0; // TODO: replace with real app ID

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
pub fn steam_unlock(_achievement_id: String) -> Result<(), SteamError> {
    if STEAM_APP_ID == 0 {
        return Err(SteamError {
            error: "steam_app_id_not_set".into(),
            hint: None,
        });
    }
    // use steamworks::Client;
    // let (client, _) = Client::init_app(STEAM_APP_ID).map_err(...)?;
    // let achievements = client.user_stats();
    // let ach = achievements.achievement(&achievement_id);
    // ach.set().map_err(...)?;
    // achievements.store_stats().map_err(...)?;
    Err(SteamError {
        error: "not_implemented_yet".into(),
        hint: None,
    })
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
