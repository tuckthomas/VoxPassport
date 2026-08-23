mod audio;
mod runtime;

use audio::{DesktopAudioCapabilities, DesktopAudioDevice};
use runtime::{RuntimeManager, RuntimeProcessStatus};

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

fn main() {
    tauri::Builder::default()
        .manage(RuntimeManager::new())
        .invoke_handler(tauri::generate_handler![
            desktop_audio_capabilities,
            desktop_audio_devices,
            local_runtime_status,
            start_local_runtime,
            stop_local_runtime,
        ])
        .run(tauri::generate_context!())
        .expect("error while running VoxPassport desktop application");
}
