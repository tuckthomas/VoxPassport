mod audio;
mod runtime;

use audio::{DesktopAudioCapabilities, DesktopAudioDevice};
use runtime::{RuntimeHttpResponse, RuntimeManager, RuntimeProcessStatus};

#[tauri::command]
fn desktop_audio_capabilities() -> DesktopAudioCapabilities {
    audio::capabilities()
}

#[tauri::command]
fn desktop_audio_devices() -> Result<Vec<DesktopAudioDevice>, String> {
    audio::devices()
}

#[tauri::command]
fn local_runtime_status(manager: tauri::State<'_, RuntimeManager>) -> RuntimeProcessStatus {
    manager.status()
}

#[tauri::command]
fn start_local_runtime(manager: tauri::State<'_, RuntimeManager>) -> Result<RuntimeProcessStatus, String> {
    manager.start()
}

#[tauri::command]
fn stop_local_runtime(manager: tauri::State<'_, RuntimeManager>) -> Result<RuntimeProcessStatus, String> {
    manager.stop()
}

#[tauri::command]
async fn local_runtime_request(
    manager: tauri::State<'_, RuntimeManager>,
    base_url: String,
    path: String,
    method: String,
    body: Option<String>,
) -> Result<RuntimeHttpResponse, String> {
    manager
        .request_local_json(&base_url, &path, &method, body.as_deref())
        .await
}

fn main() {
    tauri::Builder::default()
        .manage(RuntimeManager::new())
        .invoke_handler(tauri::generate_handler![
            desktop_audio_capabilities,
            desktop_audio_devices,
            local_runtime_status,
            start_local_runtime,
            stop_local_runtime,
            local_runtime_request,
        ])
        .run(tauri::generate_context!())
        .expect("error while running VoxPassport desktop application");
}
