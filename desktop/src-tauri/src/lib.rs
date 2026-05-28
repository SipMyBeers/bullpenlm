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
// The bundled PyInstaller sidecar's bootloader buffers stdout until
// process exit, which makes the stdout-marker pattern unreliable for
// "is it ready?" detection. We HTTP-probe this endpoint instead.
const HEALTH_PATH: &str = "/api/ollama/status";
const READY_TIMEOUT_SECS: u64 = 30;

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
    // Per-OS user-data root. paths.py inside the sidecar respects
    // BULLPENLM_HOME, so we plumb the right platform default through
    // here. Falls back to the repo dir in dev mode where data lives
    // alongside the source tree.
    let data_dir = platform_data_dir().unwrap_or_else(|| repo.clone());
    // Create the data dir before exec — Rust's spawn does chdir() before
    // running the binary, and that fails with "No such file or directory"
    // if the data dir doesn't exist yet (e.g. first-run launch).
    if let Err(e) = std::fs::create_dir_all(&data_dir) {
        log::warn!("Could not create data dir {}: {} — falling back to repo cwd", data_dir.display(), e);
    }
    log::info!("Sidecar BULLPENLM_HOME={}", data_dir.display());
    let env_vars: Vec<(&str, String)> = vec![
        // PyInstaller bootloader buffers stdout/stderr until exit. We
        // need real-time logs to surface server-ready / errors, so force
        // unbuffered mode.
        ("PYTHONUNBUFFERED", "1".to_string()),
        // User data goes here (bullpens/, training-runs/, organizations/).
        // Read-only assets stay in the bundle's _MEIPASS dir; paths.py
        // seeds them into BULLPENLM_HOME on first run.
        ("BULLPENLM_HOME", data_dir.to_string_lossy().to_string()),
    ];

    // Phase 1: try the PyInstaller-bundled sidecar first. If `sidecar(...)`
    // resolves (the binary is in the .app's resources from `externalBin`
    // in tauri.conf.json), spawn that. Otherwise fall back to system
    // `python3` (Phase 0 dev mode — repo must be on disk + Python 3
    // installed).
    let (mut rx, child) = match shell.sidecar("bullpenlm-server") {
        Ok(mut cmd) => {
            log::info!("Spawning bundled sidecar bullpenlm-server");
            for (k, v) in &env_vars { cmd = cmd.env(k, v); }
            cmd.current_dir(&data_dir)
               .spawn()
               .map_err(|e| ErrorResult {
                   ok: false,
                   error: format!("sidecar spawn failed: {}", e),
               })?
        }
        Err(sidecar_err) => {
            log::info!("Sidecar not available ({}), falling back to system python3", sidecar_err);
            let mut cmd = shell.command("python3").args(["-u", "server/server.py"]);
            for (k, v) in &env_vars { cmd = cmd.env(k, v); }
            cmd.current_dir(&repo)
                .spawn()
                .map_err(|e| ErrorResult {
                    ok: false,
                    error: format!(
                        "Neither bundled sidecar nor python3 worked. \
                         Sidecar error: {}. Python error: {}. \
                         Install Python 3 from python.org.",
                        sidecar_err, e
                    ),
                })?
        }
    };

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

    // HTTP-probe the server until it answers (READY_TIMEOUT_SECS max).
    // TCP-connect would say "ready" the moment the socket binds but that
    // happens before main() finishes wiring routes; an HTTP 200 from the
    // health endpoint means the route table is actually live.
    let url = format!("http://127.0.0.1:{}", SERVER_PORT);
    let health_url = format!("{}{}", url, HEALTH_PATH);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(READY_TIMEOUT_SECS);
    while std::time::Instant::now() < deadline {
        // Cheap reqwest-free HTTP probe via TcpStream + raw GET. Avoids
        // adding the reqwest dep just for one health check.
        if http_ok(&health_url).await {
            let _ = app.emit("server-ready", ());
            return Ok(StartHostResult {
                ok: true,
                port: SERVER_PORT,
                url,
                repo_path: repo.to_string_lossy().to_string(),
            });
        }
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
    }

    Err(ErrorResult {
        ok: false,
        error: format!(
            "Server didn't respond on {} within {}s. Check logs.",
            health_url, READY_TIMEOUT_SECS,
        ),
    })
}

/// Lightweight HTTP-GET probe. Returns true on any 2xx response.
async fn http_ok(url: &str) -> bool {
    let parsed: url::Url = match url.parse() { Ok(u) => u, Err(_) => return false };
    let host = match parsed.host_str() { Some(h) => h, None => return false };
    let port = parsed.port_or_known_default().unwrap_or(80);
    let path = if parsed.path().is_empty() { "/" } else { parsed.path() };
    let mut stream = match tokio::time::timeout(
        std::time::Duration::from_millis(800),
        tokio::net::TcpStream::connect((host, port)),
    ).await {
        Ok(Ok(s)) => s,
        _ => return false,
    };
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let req = format!(
        "GET {} HTTP/1.0\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
        path, host, port,
    );
    if stream.write_all(req.as_bytes()).await.is_err() { return false; }
    let mut head = [0u8; 16];
    if tokio::time::timeout(std::time::Duration::from_millis(800),
                             stream.read(&mut head)).await.is_err() {
        return false;
    }
    // HTTP/1.0 2xx ... — check the status digit
    head.starts_with(b"HTTP/1.0 2") || head.starts_with(b"HTTP/1.1 2")
}

/// Pick the right writable data dir per platform. Mirrors the logic
/// inside server/paths.py so dev mode and bundled mode agree on where
/// `bullpens/` etc. live.
fn platform_data_dir() -> Option<PathBuf> {
    if let Some(env_override) = std::env::var_os("BULLPENLM_HOME") {
        return Some(PathBuf::from(env_override));
    }
    #[cfg(target_os = "macos")]
    {
        let home = std::env::var_os("HOME")?;
        return Some(PathBuf::from(home)
            .join("Library").join("Application Support").join("BullpenLM"));
    }
    #[cfg(target_os = "windows")]
    {
        let appdata = std::env::var_os("APPDATA")
            .or_else(|| std::env::var_os("USERPROFILE"))?;
        return Some(PathBuf::from(appdata).join("BullpenLM"));
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let home = std::env::var_os("HOME")?;
        let xdg = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(&home).join(".local").join("share"));
        return Some(xdg.join("bullpenlm"));
    }
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
        .setup(|app| {
            // Auto-spawn the bundled sidecar on app launch AND swap the
            // webview from the static loading splash to the live server
            // root the moment the health probe succeeds. The picker is
            // bypassed entirely — / routes operator/closer to the right
            // surface (cockpit/host/spawn/quickstart) via 302.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let state: tauri::State<'_, AppState> = app_handle.state();
                match start_host(app_handle.clone(), state).await {
                    Ok(r) => {
                        log::info!("Server auto-started on {}", r.url);
                        if let Some(win) = app_handle.get_webview_window("main") {
                            if let Ok(url) = r.url.parse::<url::Url>() {
                                if let Err(e) = win.navigate(url) {
                                    log::warn!("Webview navigate to {} failed: {}", r.url, e);
                                }
                            }
                        }
                    }
                    Err(e) => log::warn!("Server auto-start failed: {}", e.error),
                }
            });
            Ok(())
        })
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
