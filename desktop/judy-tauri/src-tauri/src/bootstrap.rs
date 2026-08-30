use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

pub const API_PORT: u16 = 8090;
pub const UI_URL: &str = "http://127.0.0.1:8090/";

pub fn native_alert(title: &str, message: &str) {
    #[cfg(windows)]
    {
        windows_alert(title, message);
    }
    #[cfg(not(windows))]
    {
        macos_alert(title, message);
    }
}

#[cfg(windows)]
fn windows_alert(title: &str, message: &str) {
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(
            hwnd: *mut core::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            utype: u32,
        ) -> i32;
    }
    fn wide(s: &str) -> Vec<u16> {
        std::ffi::OsStr::new(s)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }
    let text = wide(message);
    let caption = wide(title);
    unsafe {
        MessageBoxW(null_mut(), text.as_ptr(), caption.as_ptr(), 0x10);
    }
}

pub fn macos_alert(title: &str, message: &str) {
    let script = format!(
        "display alert \"{}\" message \"{}\" as critical",
        title.replace('"', "\\\""),
        message.replace('"', "\\\"")
    );
    let _ = Command::new("osascript").args(["-e", &script]).status();
}

fn shell_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

fn bundled_python_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    if cfg!(windows) {
        let py = exe.parent()?.join("python").join("python.exe");
        return if py.is_file() { Some(py) } else { None };
    }
    let macos = exe.parent()?;
    let contents = macos.parent()?;
    let py = contents
        .join("Resources")
        .join("python")
        .join("bin")
        .join("python3");
    if py.is_file() {
        Some(py)
    } else {
        None
    }
}

fn run_login_shell(package_root: &Path, inner: &str) -> Result<i32, String> {
    let mut cmd = Command::new("/bin/zsh");
    cmd.arg("-lc")
        .arg(inner)
        .env("JUDY_ROOT", package_root)
        .env("SKILL_ROOT", package_root)
        .env("JUDY_DEPLOY", "1")
        .env("JUDY_NO_WINDOW", "1")
        .env("JUDY_DESKTOP", "1");
    if let Some(py) = bundled_python_path() {
        cmd.env("JUDY_PYTHON", &py);
        cmd.env("LINGXI_PYTHON", &py);
    }
    let status = cmd
        .status()
        .map_err(|e| format!("无法启动 shell: {e}"))?;
    Ok(status.code().unwrap_or(1))
}

fn bundled_resources() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    if cfg!(windows) {
        return exe.parent().map(|p| p.to_path_buf());
    }
    let macos = exe.parent()?;
    let contents = macos.parent()?;
    Some(contents.join("Resources"))
}

fn resolve_script(package_root: &Path, name: &str) -> Result<PathBuf, String> {
    let file = PathBuf::from(name)
        .file_name()
        .map(|s| s.to_os_string())
        .unwrap_or_default();
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Some(res) = bundled_resources() {
        cands.push(res.join("scripts").join(&file));
    }
    cands.push(
        package_root
            .join("Judy.app")
            .join("Contents")
            .join("Resources")
            .join("scripts")
            .join(&file),
    );
    cands.push(package_root.join("scripts").join(&file));
    for path in cands {
        if path.is_file() {
            return Ok(path);
        }
    }
    Err(format!("缺少脚本: {name}"))
}

fn run_bash(package_root: &Path, script: &str) -> Result<i32, String> {
    let path = resolve_script(package_root, script)?;
    let cmd = format!("bash {}", shell_single_quote(&path.display().to_string()));
    run_login_shell(package_root, &cmd)
}

fn api_healthy(port: u16) -> bool {
    Command::new("/bin/zsh")
        .args([
            "-lc",
            &format!("curl -sf http://127.0.0.1:{port}/api/health >/dev/null"),
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

pub fn wait_for_api(port: u16, timeout: Duration) -> Result<(), String> {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if api_healthy(port) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(400));
    }
    Err(format!(
        "Judy 服务在 {} 秒内未就绪。请先在解压目录运行 bash install.sh，再查看 logs/judy-api.log",
        timeout.as_secs()
    ))
}

fn python_for_package(package_root: &Path) -> Option<PathBuf> {
    if let Some(py) = bundled_python_path() {
        return Some(py);
    }
    let portable = package_root.join("python").join("python.exe");
    if portable.is_file() {
        return Some(portable);
    }
    None
}

fn api_healthy_http(port: u16, python: &Path) -> bool {
    let url = format!("http://127.0.0.1:{port}/api/health");
    Command::new(python)
        .args([
            "-c",
            &format!(
                "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('{url}', timeout=2).status<500 else 1)"
            ),
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn startup_windows(package_root: &Path) -> Result<(), String> {
    let python = python_for_package(package_root).ok_or_else(|| {
        "找不到内嵌 Python（应在 Judy.exe 同级 python\\python.exe）。请使用完整交付 zip。"
            .to_string()
    })?;
    if api_healthy_http(API_PORT, &python) {
        return Ok(());
    }
    let script = package_root.join("scripts").join("start_api.bat");
    if !script.is_file() {
        return Err(format!("缺少 {}", script.display()));
    }
    let status = Command::new("cmd")
        .args(["/C", &script.display().to_string()])
        .current_dir(package_root)
        .env("JUDY_ROOT", package_root)
        .env("JUDY_DEPLOY", "1")
        .env("JUDY_NO_WINDOW", "1")
        .env("JUDY_PYTHON", &python)
        .status()
        .map_err(|e| format!("无法启动 API: {e}"))?;
    if status.success() || api_healthy_http(API_PORT, &python) {
        return Ok(());
    }
    Err("API 启动失败。请查看 logs\\judy-api.log".into())
}

fn stop_all_windows(package_root: &Path) {
    let bat = package_root.join("scripts").join("stop_all.bat");
    if bat.is_file() {
        let _ = Command::new("cmd")
            .args(["/C", &bat.display().to_string()])
            .current_dir(package_root)
            .status();
    }
}

pub fn startup(package_root: &Path) -> Result<(), String> {
    if cfg!(windows) {
        return startup_windows(package_root);
    }
    if std::env::consts::OS != "macos" {
        return Err("Judy 桌面应用仅支持 macOS 与 Windows".into());
    }

    if api_healthy(API_PORT) {
        return Ok(());
    }

    let start_code = run_bash(package_root, "start_api.sh")?;
    if start_code != 0 {
        if api_healthy(API_PORT) {
            return Ok(());
        }
        let log = package_root.join("logs").join("judy-api.log");
        let hint = std::fs::read_to_string(&log)
            .ok()
            .map(|s| {
                let t = s.trim();
                if t.is_empty() {
                    String::new()
                } else {
                    let tail: String = t
                        .lines()
                        .rev()
                        .take(8)
                        .collect::<Vec<_>>()
                        .into_iter()
                        .rev()
                        .collect::<Vec<_>>()
                        .join("\n");
                    format!("\n\n日志摘要:\n{tail}")
                }
            })
            .unwrap_or_default();
        return Err(format!(
            "Judy 服务启动失败。请先运行 bash install.sh{hint}"
        ));
    }

    wait_for_api(API_PORT, Duration::from_secs(30))
}

pub fn stop_all(package_root: &Path) {
    if cfg!(windows) {
        stop_all_windows(package_root);
        return;
    }
    let script = match resolve_script(package_root, "stop_all.sh") {
        Ok(path) => path,
        Err(msg) => {
            eprintln!("{msg}");
            return;
        }
    };
    let inner = format!("bash {}", shell_single_quote(&script.display().to_string()));
    let _ = run_login_shell(package_root, &inner);
}
