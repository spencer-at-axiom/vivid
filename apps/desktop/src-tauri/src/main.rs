#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const SIDECAR_NAME: &str = "vivid-inference-sidecar";
const SIDECAR_HEALTH_ADDRESS: &str = "127.0.0.1:8765";
const SIDECAR_DISABLE_ENV: &str = "VIVID_DISABLE_TAURI_SIDECAR";
const SIDECAR_SMOKE_TEST_ENV: &str = "VIVID_SIDECAR_SMOKE_TEST";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum SidecarStartupState {
    Unknown,
    Running,
    Failed,
    Disabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum SidecarRuntimeMode {
    TauriDev,
    TauriPackaged,
}

struct ManagedSidecarRuntime {
    child: Option<CommandChild>,
    startup: SidecarStartupState,
    error: Option<String>,
}

impl Default for ManagedSidecarRuntime {
    fn default() -> Self {
        Self {
            child: None,
            startup: SidecarStartupState::Unknown,
            error: None,
        }
    }
}

struct ManagedSidecar(Mutex<ManagedSidecarRuntime>);

impl Default for ManagedSidecar {
    fn default() -> Self {
        Self(Mutex::new(ManagedSidecarRuntime::default()))
    }
}

#[derive(Debug, Clone, Serialize)]
struct ManagedSidecarStatusPayload {
    mode: SidecarRuntimeMode,
    startup: SidecarStartupState,
    managed: bool,
    error: Option<String>,
    sidecar_name: String,
}

fn is_truthy_flag(raw: &str) -> bool {
    matches!(raw.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on")
}

fn env_flag(name: &str) -> bool {
    std::env::var(name).map(|value| is_truthy_flag(&value)).unwrap_or(false)
}

fn runtime_mode_from_build_flag(debug_build: bool) -> SidecarRuntimeMode {
    if debug_build {
        SidecarRuntimeMode::TauriDev
    } else {
        SidecarRuntimeMode::TauriPackaged
    }
}

fn runtime_mode() -> SidecarRuntimeMode {
    runtime_mode_from_build_flag(cfg!(debug_assertions))
}

fn sidecar_filename_for_host() -> String {
    if cfg!(target_os = "windows") {
        format!("{SIDECAR_NAME}.exe")
    } else {
        SIDECAR_NAME.to_string()
    }
}

fn sidecar_binary_path_from_current_exe() -> Result<PathBuf, String> {
    let current_exe = std::env::current_exe().map_err(|error| format!("failed to resolve current executable: {error}"))?;
    let parent = current_exe
        .parent()
        .ok_or_else(|| "failed to resolve executable parent directory".to_string())?;
    Ok(parent.join(sidecar_filename_for_host()))
}

fn should_skip_sidecar() -> bool {
    env_flag(SIDECAR_DISABLE_ENV)
}

fn should_run_sidecar_smoke_test() -> bool {
    env_flag(SIDECAR_SMOKE_TEST_ENV)
}

fn set_sidecar_runtime(
    app: &AppHandle,
    startup: SidecarStartupState,
    error: Option<String>,
    child: Option<CommandChild>,
) -> Result<(), String> {
    let sidecar_state = app.state::<ManagedSidecar>();
    let mut guard = sidecar_state
        .0
        .lock()
        .map_err(|_| "failed to lock sidecar state".to_string())?;
    guard.startup = startup;
    guard.error = error;
    if child.is_some() {
        guard.child = child;
    } else if startup != SidecarStartupState::Running {
        guard.child = None;
    }
    Ok(())
}

fn probe_sidecar_health(timeout: Duration) -> bool {
    let address: SocketAddr = match SIDECAR_HEALTH_ADDRESS.parse() {
        Ok(parsed) => parsed,
        Err(_) => return false,
    };
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(300)));
            let _ = stream.set_write_timeout(Some(Duration::from_millis(300)));
            let request = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(request).is_ok() {
                let mut buffer = [0_u8; 256];
                if let Ok(read_len) = stream.read(&mut buffer) {
                    if read_len > 0 {
                        let response = String::from_utf8_lossy(&buffer[..read_len]);
                        if response.contains(" 200 ") || response.contains("\n200 ") {
                            return true;
                        }
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

fn run_sidecar_smoke_test() -> i32 {
    let sidecar_path = match sidecar_binary_path_from_current_exe() {
        Ok(path) => path,
        Err(error) => {
            eprintln!("[sidecar][smoke] {error}");
            return 1;
        }
    };
    if !sidecar_path.exists() {
        eprintln!(
            "[sidecar][smoke] expected bundled sidecar binary at '{}'",
            sidecar_path.display()
        );
        return 1;
    }

    let mut child = match Command::new(&sidecar_path)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(process) => process,
        Err(error) => {
            eprintln!("[sidecar][smoke] failed to launch sidecar '{}': {error}", sidecar_path.display());
            return 1;
        }
    };

    let healthy = probe_sidecar_health(Duration::from_secs(20));
    if let Err(error) = child.kill() {
        eprintln!("[sidecar][smoke] failed to kill sidecar process: {error}");
    }
    let _ = child.wait();
    if healthy {
        println!("[sidecar][smoke] bundled sidecar healthcheck passed");
        0
    } else {
        eprintln!("[sidecar][smoke] bundled sidecar healthcheck did not become healthy in time");
        1
    }
}

fn start_managed_sidecar(app: &AppHandle) -> Result<(), String> {
    let sidecar_command = app
        .shell()
        .sidecar(SIDECAR_NAME)
        .map_err(|error| format!("failed to configure sidecar '{SIDECAR_NAME}': {error}"))?;
    let (mut rx, child) = sidecar_command
        .spawn()
        .map_err(|error| format!("failed to spawn sidecar '{SIDECAR_NAME}': {error}"))?;

    set_sidecar_runtime(app, SidecarStartupState::Running, None, Some(child))?;

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[sidecar] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[sidecar][stderr] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(message) => {
                    eprintln!("[sidecar][error] {message}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!(
                        "[sidecar] terminated (code: {:?}, signal: {:?})",
                        payload.code, payload.signal
                    );
                    let reason = format!(
                        "Sidecar process terminated (code: {:?}, signal: {:?}).",
                        payload.code, payload.signal
                    );
                    let _ = set_sidecar_runtime(
                        &app_handle,
                        SidecarStartupState::Failed,
                        Some(reason),
                        None,
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

fn stop_managed_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<ManagedSidecar>() {
        if let Ok(mut sidecar) = state.0.lock() {
            if let Some(child) = sidecar.child.take() {
                if let Err(error) = child.kill() {
                    eprintln!("[sidecar] failed to kill child process: {error}");
                }
            }
            sidecar.startup = SidecarStartupState::Unknown;
            sidecar.error = None;
        }
    }
}

#[tauri::command]
fn managed_sidecar_status(state: State<'_, ManagedSidecar>) -> ManagedSidecarStatusPayload {
    if let Ok(guard) = state.0.lock() {
        return ManagedSidecarStatusPayload {
            mode: runtime_mode(),
            startup: guard.startup,
            managed: guard.startup != SidecarStartupState::Disabled,
            error: guard.error.clone(),
            sidecar_name: SIDECAR_NAME.to_string(),
        };
    }

    ManagedSidecarStatusPayload {
        mode: runtime_mode(),
        startup: SidecarStartupState::Failed,
        managed: true,
        error: Some("failed to lock sidecar runtime state".to_string()),
        sidecar_name: SIDECAR_NAME.to_string(),
    }
}

fn main() {
    if should_run_sidecar_smoke_test() {
        std::process::exit(run_sidecar_smoke_test());
    }

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![managed_sidecar_status])
        .setup(|app| {
            app.manage(ManagedSidecar::default());
            if should_skip_sidecar() {
                let _ = set_sidecar_runtime(app.handle(), SidecarStartupState::Disabled, None, None);
                eprintln!("[sidecar] startup disabled via VIVID_DISABLE_TAURI_SIDECAR");
                return Ok(());
            }

            if let Err(error) = start_managed_sidecar(app.handle()) {
                let _ = set_sidecar_runtime(
                    app.handle(),
                    SidecarStartupState::Failed,
                    Some(error.clone()),
                    None,
                );
                eprintln!("[sidecar] managed startup failed: {error}");
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            stop_managed_sidecar(app);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truthy_flag_parser_supports_expected_values() {
        assert!(is_truthy_flag("1"));
        assert!(is_truthy_flag("true"));
        assert!(is_truthy_flag("YES"));
        assert!(is_truthy_flag(" on "));
        assert!(!is_truthy_flag("0"));
        assert!(!is_truthy_flag("false"));
        assert!(!is_truthy_flag(""));
    }

    #[test]
    fn runtime_mode_mapping_supports_dev_and_packaged() {
        assert_eq!(
            runtime_mode_from_build_flag(true),
            SidecarRuntimeMode::TauriDev
        );
        assert_eq!(
            runtime_mode_from_build_flag(false),
            SidecarRuntimeMode::TauriPackaged
        );
    }

    #[test]
    fn sidecar_filename_matches_host_platform() {
        if cfg!(target_os = "windows") {
            assert_eq!(sidecar_filename_for_host(), "vivid-inference-sidecar.exe");
        } else {
            assert_eq!(sidecar_filename_for_host(), "vivid-inference-sidecar");
        }
    }
}
