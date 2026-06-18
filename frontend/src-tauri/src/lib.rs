//! Tauri sidecar supervision for Find desktop application.
//! Spawns and supervises the FastAPI backend process.

use tauri::Manager;
use tauri::Emitter;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// Shared state tracking whether the backend sidecar is running.
#[derive(Default)]
struct BackendState {
    running: bool,
}

type SharedState = Arc<Mutex<BackendState>>;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let state: SharedState = Arc::new(Mutex::new(BackendState::default()));
            app.manage(state.clone());
            let app_handle = app.handle().clone();
            let state_clone = state.clone();
            tauri::async_runtime::spawn(async move {
                supervise_backend(app_handle, state_clone).await;
            });
            Ok(())
        })
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                log::info!("Window destroyed - backend sidecar will be cleaned up.");
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Supervises the backend sidecar process with automatic restart on crash.
///
/// Retries up to `MAX_RETRIES` times with a `RETRY_DELAY_SECS` delay between attempts.
/// Emits `backend-failed` event to the frontend if all retries are exhausted.
async fn supervise_backend(app: tauri::AppHandle, state: SharedState) {
    const MAX_RETRIES: u32 = 5;
    const RETRY_DELAY_SECS: u64 = 2;
    let mut retry_count = 0;
    loop {
        log::info!("Starting backend sidecar (attempt {})...", retry_count + 1);
        match start_sidecar(&app, &state).await {
            Ok(_) => {
                log::info!("Backend sidecar exited cleanly.");
                state.lock().unwrap().running = false;
                break;
            }
            Err(e) => {
                state.lock().unwrap().running = false;
                retry_count += 1;
                log::error!("Backend crashed: {}. Retry {}/{}", e, retry_count, MAX_RETRIES);
                if retry_count >= MAX_RETRIES {
                    log::error!("Backend failed {} times - giving up.", MAX_RETRIES);
                    let _ = app.emit("backend-failed", "Backend crashed too many times");
                    break;
                }
                tokio::time::sleep(Duration::from_secs(RETRY_DELAY_SECS)).await;
            }
        }
    }
}

/// Spawns the backend sidecar and monitors its output until termination.
///
/// Emits `backend-ready` to the frontend once the process starts successfully.
/// Returns `Ok(())` on clean exit (code 0), or `Err` on crash or error.
async fn start_sidecar(app: &tauri::AppHandle, state: &SharedState) -> Result<(), String> {
    let shell = app.shell();
    let (mut rx, _child) = shell
        .sidecar("find-backend")
        .map_err(|e| format!("Failed to create sidecar: {}", e))?
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar: {}", e))?;
    state.lock().unwrap().running = true;
    log::info!("Backend sidecar spawned.");
    let _ = app.emit("backend-ready", ());
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => log::info!("[backend] {}", String::from_utf8_lossy(&line).trim()),
            CommandEvent::Stderr(line) => log::warn!("[backend err] {}", String::from_utf8_lossy(&line).trim()),
            CommandEvent::Error(err) => return Err(format!("Sidecar error: {}", err)),
            CommandEvent::Terminated(payload) => {
                let code = payload.code.unwrap_or(-1);
                return if code == 0 { Ok(()) } else { Err(format!("Exited with code {}", code)) };
            }
            _ => {}
        }
    }
    Ok(())
}
