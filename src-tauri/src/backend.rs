use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex, mpsc},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
#[cfg(not(debug_assertions))]
use tauri::Manager;
use tauri::{AppHandle, State, WebviewWindow};

#[derive(Clone, Deserialize, Serialize)]
pub struct Connection {
    base_url: String,
    token: String,
}

fn parse_connection(line: &str) -> Result<Connection, String> {
    let connection: Connection =
        serde_json::from_str(line).map_err(|_| "Kết nối bộ xử lý không hợp lệ.")?;
    let port = connection
        .base_url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|port| *port > 0);
    if port.is_none()
        || !(32..=256).contains(&connection.token.len())
        || !connection
            .token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err("Kết nối bộ xử lý không hợp lệ.".into());
    }
    Ok(connection)
}

struct Running {
    child: Child,
    connection: Connection,
    directory: PathBuf,
    session: PathBuf,
}

fn cleanup_session(directory: &Path, session: &Path) {
    let (Ok(base), Ok(temporary), Ok(target)) = (
        directory.canonicalize(),
        directory.join("tmp").canonicalize(),
        session.canonicalize(),
    ) else {
        return;
    };
    if temporary.parent() != Some(base.as_path())
        || target.parent() != Some(temporary.as_path())
        || !target
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.starts_with("session-"))
    {
        return;
    }
    for _ in 0..20 {
        match fs::remove_dir_all(&target) {
            Ok(()) => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
            Err(_) => std::thread::sleep(Duration::from_millis(100)),
        }
    }
}

fn stop(child: &mut Child) {
    if !matches!(child.try_wait(), Ok(None)) {
        let _ = child.wait();
        return;
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[derive(Clone, Default)]
pub struct BackendState(Arc<Mutex<Option<Running>>>);

impl BackendState {
    pub fn shutdown(&self) {
        if let Ok(mut state) = self.0.lock() {
            if let Some(mut running) = state.take() {
                stop(&mut running.child);
                cleanup_session(&running.directory, &running.session);
            }
        }
    }

    fn connection(&self, _app: &AppHandle) -> Result<Connection, String> {
        let mut state = self.0.lock().map_err(|_| "Bộ xử lý đang bận.")?;
        if let Some(running) = state.as_mut() {
            if matches!(running.child.try_wait(), Ok(None)) {
                return Ok(running.connection.clone());
            }
        }
        if let Some(mut previous) = state.take() {
            stop(&mut previous.child);
            cleanup_session(&previous.directory, &previous.session);
        }
        #[cfg(debug_assertions)]
        let default_directory = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("data/inspections");
        #[cfg(not(debug_assertions))]
        let default_directory = _app
            .path()
            .app_local_data_dir()
            .map_err(|_| "Không mở được thư mục ứng dụng.")?
            .join("inspections");
        let directory = std::env::var_os("BIM_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or(default_directory);
        fs::create_dir_all(&directory).map_err(|_| "Không tạo được thư mục kết quả.")?;
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "Không tạo được phiên xử lý.")?
            .as_nanos();
        let session_id = format!("session-{}-{}", std::process::id(), stamp);
        let session = directory.join("tmp").join(&session_id);
        let log = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(directory.join("processor.log"))
            .map_err(|_| "Không mở được nhật ký xử lý.")?;
        #[cfg(debug_assertions)]
        let mut command = {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap();
            let mut command = Command::new(root.join(".venv/Scripts/python.exe"));
            command.args(["-m", "app"]).current_dir(root);
            command
        };
        #[cfg(not(debug_assertions))]
        let mut command = Command::new(
            _app.path()
                .resource_dir()
                .map_err(|_| "Không tìm thấy bộ xử lý.")?
                .join("backend/bim_backend.exe"),
        );
        command
            .args(["--desktop", "--parent-pid", &std::process::id().to_string()])
            .env("BIM_DATA_DIR", &directory)
            .env("BIM_SESSION_ID", &session_id)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log));
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command
            .spawn()
            .map_err(|_| "Không khởi động được bộ xử lý. Hãy mở lại bản cài ứng dụng.")?;
        let stdout = child.stdout.take().ok_or("Không kết nối được bộ xử lý.")?;
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let mut line = String::new();
            let _ = BufReader::new(stdout).take(4096).read_line(&mut line);
            let _ = sender.send(line);
        });
        let result = receiver
            .recv_timeout(Duration::from_secs(15))
            .map_err(|_| "Bộ xử lý khởi động quá lâu.".to_string())
            .and_then(|line| parse_connection(&line));
        match result {
            Ok(connection) => {
                *state = Some(Running {
                    child,
                    connection: connection.clone(),
                    directory,
                    session,
                });
                Ok(connection)
            }
            Err(error) => {
                stop(&mut child);
                cleanup_session(&directory, &session);
                Err(error)
            }
        }
    }
}

#[tauri::command]
pub async fn backend_connection(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, BackendState>,
) -> Result<Connection, String> {
    if window.label() != "main" {
        return Err("Cửa sổ không được phép kết nối.".into());
    }
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || state.connection(&app))
        .await
        .map_err(|_| "Không kết nối được bộ xử lý.")?
}

#[cfg(test)]
mod tests {
    use super::parse_connection;

    #[test]
    fn rejects_remote_or_invalid_processor_handshake() {
        assert!(parse_connection(r#"{"base_url":"https://example.com","token":"abcdefghijklmnopqrstuvwxyz1234567890"}"#).is_err());
        assert!(parse_connection(r#"{"base_url":"http://127.0.0.1:0","token":"abcdefghijklmnopqrstuvwxyz1234567890"}"#).is_err());
        assert!(
            parse_connection(r#"{"base_url":"http://127.0.0.1:12345","token":"short"}"#).is_err()
        );
        assert!(parse_connection(r#"{"base_url":"http://127.0.0.1:12345","token":"abcdefghijklmnopqrstuvwxyz1234567890"}"#).is_ok());
    }
}
