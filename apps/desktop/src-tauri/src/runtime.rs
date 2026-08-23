use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeProcessStatus {
    pub base_url: String,
    pub owned_by_desktop: bool,
    pub running: bool,
    pub pid: Option<u32>,
}

pub struct RuntimeManager {
    child: Mutex<Option<Child>>,
    project_root: PathBuf,
    base_url: String,
}

impl RuntimeManager {
    pub fn new() -> Self {
        let project_root = std::env::var_os("VOXPASSPORT_PROJECT_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(default_project_root);
        let base_url = std::env::var("VOXPASSPORT_LOCAL_RUNTIME_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8766".to_string());
        Self {
            child: Mutex::new(None),
            project_root,
            base_url,
        }
    }

    pub fn status(&self) -> RuntimeProcessStatus {
        let mut guard = self.child.lock().expect("runtime child mutex poisoned");
        let (running, pid) = match guard.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(None) => (true, Some(child.id())),
                Ok(Some(_)) | Err(_) => {
                    *guard = None;
                    (false, None)
                }
            },
            None => (false, None),
        };
        RuntimeProcessStatus {
            base_url: self.base_url.clone(),
            owned_by_desktop: running,
            running,
            pid,
        }
    }

    pub fn start(&self) -> Result<RuntimeProcessStatus, String> {
        let existing = self.status();
        if existing.running {
            return Ok(existing);
        }

        let python = std::env::var_os("VOXPASSPORT_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| default_python(&self.project_root));
        if !python.exists() {
            return Err(format!(
                "VoxPassport Python interpreter not found at {}. Set VOXPASSPORT_PYTHON to override it.",
                python.display()
            ));
        }

        let child = Command::new(&python)
            .current_dir(&self.project_root)
            .arg("-m")
            .arg("runtime.inference.server.main")
            .arg("--data-dir")
            .arg("data")
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| format!("Could not start VoxPassport local runtime: {error}"))?;

        let mut guard = self.child.lock().map_err(|_| "runtime child mutex poisoned".to_string())?;
        *guard = Some(child);
        drop(guard);
        Ok(self.status())
    }

    pub fn stop(&self) -> Result<RuntimeProcessStatus, String> {
        let mut guard = self.child.lock().map_err(|_| "runtime child mutex poisoned".to_string())?;
        if let Some(mut child) = guard.take() {
            if child.try_wait().map_err(|error| error.to_string())?.is_none() {
                child.kill().map_err(|error| format!("Could not stop VoxPassport runtime: {error}"))?;
                let _ = child.wait();
            }
        }
        drop(guard);
        Ok(self.status())
    }
}

impl Drop for RuntimeManager {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn default_project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .expect("desktop crate must remain under apps/desktop/src-tauri")
        .to_path_buf()
}

fn default_python(project_root: &Path) -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        return project_root.join(".venv").join("Scripts").join("python.exe");
    }
    #[cfg(not(target_os = "windows"))]
    {
        project_root.join(".venv").join("bin").join("python")
    }
}
