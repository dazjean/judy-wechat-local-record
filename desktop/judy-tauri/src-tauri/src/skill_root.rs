use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;

const MARKER: &str = "JUDY_ROOT";

fn looks_like_package_root(path: &Path) -> bool {
    if !path.is_dir() {
        return false;
    }
    let app = path.join("Judy.app");
    if app.is_dir() {
        let res = app.join("Contents").join("Resources");
        if res.join("backend").is_dir() && res.join("web").is_dir() {
            return true;
        }
        if path.join("install.sh").is_file() || path.join("使用说明.md").is_file() {
            return true;
        }
    }
    path.join("backend").is_dir()
        && (path.join("web").is_dir() || path.join("frontend").is_dir())
}

fn app_bundle_candidates(bundle: &Path) -> Result<Vec<PathBuf>, String> {
    let bundle = bundle
        .canonicalize()
        .map_err(|e| format!("无法解析 .app 路径: {e}"))?;
    let mut candidates: Vec<PathBuf> = Vec::new();
    let mut seen: Vec<PathBuf> = Vec::new();

    let mut add = |raw: PathBuf| {
        if seen.iter().any(|p| p == &raw) {
            return;
        }
        seen.push(raw.clone());
        candidates.push(raw);
    };

    let marker = bundle.parent().unwrap_or(bundle.as_path()).join(MARKER);
    if marker.is_file() {
        if let Ok(text) = std::fs::read_to_string(&marker) {
            if let Some(line) = text.lines().next() {
                let line = line.trim();
                if !line.is_empty() {
                    add(PathBuf::from(line));
                }
            }
        }
    }

    add(bundle.clone());
    let mut current = bundle
        .parent()
        .unwrap_or(bundle.as_path())
        .to_path_buf();
    for _ in 0..24 {
        add(current.clone());
        if !current.pop() {
            break;
        }
    }

    Ok(candidates)
}

fn resolve_without_python(
    env_root: Option<&str>,
    app_bundle: Option<&Path>,
) -> Result<PathBuf, String> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(raw) = env_root {
        candidates.push(PathBuf::from(raw));
    }

    if let Some(bundle) = app_bundle {
        candidates.extend(app_bundle_candidates(bundle)?);
    }

    let tried = candidates
        .iter()
        .map(|p| p.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");

    for raw in &candidates {
        let path = raw.canonicalize().unwrap_or_else(|_| raw.clone());
        if looks_like_package_root(&path) {
            return Ok(path);
        }
    }

    Err(format!(
        "无法定位 Judy 安装目录（需含 Judy.app）。已尝试: {tried}"
    ))
}

pub fn locate_package_root_py(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Ok(dir) = app.path().resource_dir() {
        for name in ["package_root.py", "skill_root.py"] {
            let bundled = dir.join(name);
            if bundled.is_file() {
                return Ok(bundled);
            }
        }
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for candidate in [
        manifest.join("resources/package_root.py"),
        manifest.join("../../shared/package_root.py"),
    ] {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }

    Err("缺少 package_root.py（Resources 或开发目录）".into())
}

fn python_interpreters(app_bundle: Option<&Path>) -> Vec<PathBuf> {
    let mut cmds: Vec<PathBuf> = Vec::new();
    if let Some(bundle) = app_bundle {
        let win = bundle.join("python").join("python.exe");
        if win.is_file() {
            cmds.push(win);
        }
        let mac = bundle
            .join("Contents")
            .join("Resources")
            .join("python")
            .join("bin")
            .join("python3");
        if mac.is_file() {
            cmds.push(mac);
        }
    }
    cmds.push(PathBuf::from("python3"));
    cmds.push(PathBuf::from("python"));
    cmds
}

pub fn resolve(app: &tauri::AppHandle, app_bundle: Option<&Path>) -> Result<PathBuf, String> {
    let env_root = std::env::var("JUDY_ROOT")
        .ok()
        .or_else(|| std::env::var("SKILL_ROOT").ok());

    if let Ok(py) = locate_package_root_py(app) {
        for interpreter in python_interpreters(app_bundle) {
            let mut cmd = Command::new(&interpreter);
            cmd.arg(&py).arg("--print");
            if let Some(bundle) = app_bundle {
                cmd.arg("--app-bundle").arg(bundle);
            }
            if let Some(root) = env_root.as_deref() {
                cmd.env("JUDY_ROOT", root);
            }

            let Ok(output) = cmd.output() else {
                continue;
            };
            if output.status.success() {
                let line = String::from_utf8_lossy(&output.stdout).trim().to_string();
                if !line.is_empty() {
                    let path = PathBuf::from(&line);
                    if looks_like_package_root(&path) {
                        return Ok(path);
                    }
                }
            }
        }
    }

    resolve_without_python(env_root.as_deref(), app_bundle)
}

pub fn app_bundle_from_exe() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let exe = exe.canonicalize().ok()?;
    #[cfg(windows)]
    {
        return exe.parent().map(|p| p.to_path_buf());
    }
    #[cfg(not(windows))]
    {
        let mut path = exe.as_path();
        while path.parent().is_some() {
            if path.extension().and_then(|s| s.to_str()) == Some("app") {
                return Some(path.to_path_buf());
            }
            path = path.parent()?;
        }
        None
    }
}
