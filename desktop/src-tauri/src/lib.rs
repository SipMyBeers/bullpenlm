//! BullpenLM desktop wrapper.
//!
//! The Tauri app exists for one reason: friends shouldn't have to know how
//! to clone a repo, run `python3 server/server.py`, expose a port, or find
//! a Tailscale IP. They double-click an icon. The picker UI asks Host or
//! Join. Host spawns the bundled Python server (+ cloudflared via the
//! server's own /api/host/publish endpoint); Join skips the server and
//! navigates the webview to the founder's tunnel URL.
//!
//! Bundling note (v0.1): this build shells out to `python3` on PATH and
//! expects the repo at $BULLPENLM_REPO, then ~/bullpenlm, then ./.. .
//! v0.2 will ship a PyInstaller'd sidecar binary so users don't need
//! Python pre-installed.

use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// Steam integration is feature-gated. The open-source self-host build
// (default) doesn't compile this module or pull the steamworks crate.
// Phase 2 (Steam EA) builds enable it with `tauri build --features steam`.
#[cfg(feature = "steam")]
mod steam;

const SERVER_PORT: u16 = 7878;
const SERVER_READY_MARKER: &str = "BullpenLM · trainer";

#[derive(Default)]
struct AppState {
    server: Mutex<Option<CommandChild>>,
}

#[derive(serde::Serialize, Clone)]
struct StartHostResult {
    ok: bool,
    port: u16,
    url: String,
    repo_path: String,
}

#[derive(serde::Serialize, Clone)]
struct ErrorResult {
    ok: bool,
    error: String,
}

/// Find the BullpenLM repo on disk. v0.1 dev mode — checks env var,
/// home dir, and parent of the .app's resources.
fn locate_repo() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("BULLPENLM_REPO") {
        let path = PathBuf::from(p);
        if path.join("server").join("server.py").exists() {
            return Ok(path);
        }
    }
    if let Some(home) = std::env::var_os("HOME") {
        let p = PathBuf::from(home).join("bullpenlm");
        if p.join("server").join("server.py").exists() {
            return Ok(p);
        }
    }
    // Walk up from the executable, in case the .app is sitting next to the repo
    if let Ok(exe) = std::env::current_exe() {
        let mut cur: Option<&std::path::Path> = exe.parent();
        for _ in 0..6 {
            if let Some(c) = cur {
                let candidate = c.join("server").join("server.py");
                if candidate.exists() {
                    return Ok(c.to_path_buf());
                }
                cur = c.parent();
            } else {
                break;
            }
        }
    }
    Err("BULLPENLM_REPO not set and no repo found at ~/bullpenlm".to_string())
}

/// Start the Python server as a child process. Streams stdout/stderr to
/// log, waits for the port to bind, then resolves with the localhost URL.
#[tauri::command]
async fn start_host(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<StartHostResult, ErrorResult> {
    // Already running?
    {
        let guard = state.server.lock().unwrap();
        if guard.is_some() {
            return Ok(StartHostResult {
                ok: true,
                port: SERVER_PORT,
                url: format!("http://127.0.0.1:{}", SERVER_PORT),
                repo_path: locate_repo().unwrap_or_default().to_string_lossy().to_string(),
            });
        }
    }

    let repo = locate_repo().map_err(|e| ErrorResult { ok: false, error: e })?;
    log::info!("Starting Python server with cwd={}", repo.display());

    let shell = app.shell();
    let (mut rx, child) = shell
        .command("python3")
        .args(["-u", "server/server.py"])
        .current_dir(&repo)
        .spawn()
        .map_err(|e| ErrorResult {
            ok: false,
            error: format!("python3 spawn failed: {}. Install Python 3 from python.org.", e),
        })?;

    {
        let mut guard = state.server.lock().unwrap();
        *guard = Some(child);
    }

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut ready_sent = false;
        while let Some(ev) = rx.recv().await {
            match ev {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(&line);
                    log::info!("[server] {}", text.trim_end());
                    if !ready_sent && text.contains(SERVER_READY_MARKER) {
                        ready_sent = true;
                        let _ = app_handle.emit("server-ready", ());
                    }
                }
                CommandEvent::Error(e) => log::error!("[server] error: {}", e),
                CommandEvent::Terminated(payload) => {
                    log::warn!("[server] terminated: {:?}", payload);
                    let _ = app_handle.emit("server-stopped", ());
                    break;
                }
                _ => {}
            }
        }
    });

    // Port-poll until the server accepts connections (12s max).
    let url = format!("http://127.0.0.1:{}", SERVER_PORT);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(12);
    while std::time::Instant::now() < deadline {
        if tokio::net::TcpStream::connect(("127.0.0.1", SERVER_PORT)).await.is_ok() {
            return Ok(StartHostResult {
                ok: true,
                port: SERVER_PORT,
                url,
                repo_path: repo.to_string_lossy().to_string(),
            });
        }
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    Err(ErrorResult {
        ok: false,
        error: format!("Server didn't bind to 127.0.0.1:{} within 12s. Check logs.", SERVER_PORT),
    })
}

#[tauri::command]
async fn stop_host(state: tauri::State<'_, AppState>) -> Result<(), ()> {
    let child = {
        let mut guard = state.server.lock().unwrap();
        guard.take()
    };
    if let Some(c) = child {
        let _ = c.kill();
    }
    Ok(())
}

#[tauri::command]
fn host_status(state: tauri::State<'_, AppState>) -> serde_json::Value {
    let guard = state.server.lock().unwrap();
    serde_json::json!({ "running": guard.is_some(), "port": SERVER_PORT })
}

/// Swap the main webview over to the floor (or join) URL after the picker.
/// Uses webview.navigate which is the proper Tauri 2 API for this.
#[tauri::command]
async fn open_floor(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let parsed: url::Url = url.parse().map_err(|e: url::ParseError| e.to_string())?;
    if let Some(win) = app.get_webview_window("main") {
        win.navigate(parsed)
            .map_err(|e| format!("navigate failed: {}", e))?;
    } else {
        let _ = WebviewWindowBuilder::new(&app, "floor", WebviewUrl::External(parsed))
            .title("BullpenLM · The Floor")
            .inner_size(1200.0, 800.0)
            .build();
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(AppState::default())
        .invoke_handler({
            // Open-source self-host handlers are always wired. Steam-only
            // commands are registered in a feature-gated branch so the
            // FOSS build's handler table doesn't reference missing fns.
            #[cfg(not(feature = "steam"))]
            { tauri::generate_handler![start_host, stop_host, host_status, open_floor] }
            #[cfg(feature = "steam")]
            { tauri::generate_handler![
                start_host, stop_host, host_status, open_floor,
                steam::steam_init,
                steam::steam_unlock,
                steam::steam_cloud_push,
                steam::steam_cloud_pull,
                steam::steam_invite_friend,
            ] }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Clean up the spawned Python server on quit.
                if let Some(state) = app_handle.try_state::<AppState>() {
                    let child = {
                        let mut guard = state.server.lock().unwrap();
                        guard.take()
                    };
                    if let Some(c) = child {
                        log::info!("Killing Python server on exit");
                        let _ = c.kill();
                    }
                }
            }
        });
}
