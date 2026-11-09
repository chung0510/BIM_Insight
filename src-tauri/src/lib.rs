mod backend;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(backend::BackendState::default())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend::backend_connection])
        .build(tauri::generate_context!())
        .expect("error while building application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                app.state::<backend::BackendState>().shutdown();
            }
        });
}
