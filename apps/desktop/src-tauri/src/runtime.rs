use reqwest::header::{ACCEPT, CONTENT_TYPE};
use reqwest::{Method, Url};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeProcessStatus {
    pub base_url: String,
    pub owned_by_desktop: bool,
    pub running: bool,
    pub pid: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeHttpResponse {
    pub status: u16,
    pub content_type: Option<String>,
    pub body: String,
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

    pub async fn request_local_json(
        &self,
        base_url: &str,
        path: &str,
        method: &str,
        body: Option<&str>,
    ) -> Result<RuntimeHttpResponse, String> {
        let base = validate_loopback_base_url(base_url)?;
        validate_api_path(path)?;
        let method = parse_allowed_method(method)?;
        let url = base
            .join(path.trim_start_matches('/'))
            .map_err(|error| format!("Invalid local runtime API URL: {error}"))?;

        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(120))
            .build()
            .map_err(|error| format!("Could not create local runtime HTTP client: {error}"))?;

        let mut request = client
            .request(method, url)
            .header(ACCEPT, "application/json");
        if let Some(body) = body {
            request = request
                .header(CONTENT_TYPE, "application/json")
                .body(body.to_owned());
        }

        let response = request
            .send()
            .await
            .map_err(|error| format!("Local runtime request failed: {error}"))?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let body = response
            .text()
            .await
            .map_err(|error| format!("Could not read local runtime response: {error}"))?;

        Ok(RuntimeHttpResponse {
            status,
            content_type,
            body,
        })
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

fn validate_loopback_base_url(value: &str) -> Result<Url, String> {
    let mut url = Url::parse(value).map_err(|error| format!("Invalid local runtime URL: {error}"))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err("Local runtime URL must use http or https".to_string());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("Local runtime URL must not contain embedded credentials".to_string());
    }
    let host = url
        .host_str()
        .ok_or_else(|| "Local runtime URL must include a host".to_string())?;
    if !matches!(host, "localhost" | "127.0.0.1" | "::1") {
        return Err("Native local-runtime transport only permits loopback hosts".to_string());
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err("Local runtime base URL must not contain a query or fragment".to_string());
    }
    url.set_path("/");
    Ok(url)
}

fn validate_api_path(path: &str) -> Result<(), String> {
    if !path.starts_with("/api/") {
        return Err("Native runtime transport only permits /api/ paths".to_string());
    }
    if path.contains("..") || path.contains("\\") || path.contains("://") {
        return Err("Invalid local runtime API path".to_string());
    }
    if path.chars().any(char::is_control) {
        return Err("Local runtime API path contains control characters".to_string());
    }
    Ok(())
}

fn parse_allowed_method(value: &str) -> Result<Method, String> {
    match value.trim().to_ascii_uppercase().as_str() {
        "GET" => Ok(Method::GET),
        "POST" => Ok(Method::POST),
        "DELETE" => Ok(Method::DELETE),
        _ => Err("Native local-runtime transport permits GET, POST, and DELETE only".to_string()),
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

#[cfg(test)]
mod tests {
    use super::{parse_allowed_method, validate_api_path, validate_loopback_base_url};

    #[test]
    fn native_proxy_accepts_loopback_only() {
        assert!(validate_loopback_base_url("http://127.0.0.1:8766").is_ok());
        assert!(validate_loopback_base_url("http://localhost:8766").is_ok());
        assert!(validate_loopback_base_url("http://[::1]:8766").is_ok());
        assert!(validate_loopback_base_url("https://example.com").is_err());
        assert!(validate_loopback_base_url("http://192.168.1.25:8766").is_err());
    }

    #[test]
    fn native_proxy_accepts_api_paths_only() {
        assert!(validate_api_path("/api/status").is_ok());
        assert!(validate_api_path("/api/models/progress?model_id=x").is_ok());
        assert!(validate_api_path("/manager/index.html").is_err());
        assert!(validate_api_path("/api/../manager").is_err());
    }

    #[test]
    fn native_proxy_limits_methods() {
        assert!(parse_allowed_method("GET").is_ok());
        assert!(parse_allowed_method("post").is_ok());
        assert!(parse_allowed_method("DELETE").is_ok());
        assert!(parse_allowed_method("CONNECT").is_err());
    }
}
