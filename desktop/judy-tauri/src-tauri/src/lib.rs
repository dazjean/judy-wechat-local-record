mod bootstrap;
mod skill_root;

use bootstrap::{native_alert, stop_all, startup, UI_URL};
use skill_root::{app_bundle_from_exe, resolve};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, WindowEvent,
};

struct AppState {
    skill_root: PathBuf,
}

static QUITTING: AtomicBool = AtomicBool::new(false);

fn request_quit(app: &tauri::AppHandle) {
    if QUITTING.swap(true, Ordering::SeqCst) {
        return;
    }
    app.exit(0);
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_bundle = app_bundle_from_exe();
            let skill_root = match resolve(app.handle(), app_bundle.as_deref()) {
                Ok(root) => root,
                Err(msg) => {
                    native_alert(
                        "Judy",
                        "找不到安装目录。请将「Judy.app」放在解压后的 zip 根目录，或设置环境变量 JUDY_ROOT。",
                    );
                    eprintln!("{msg}");
                    app.handle().exit(1);
                    return Ok(());
                }
            };

            if let Err(msg) = startup(&skill_root) {
                native_alert("Judy", &msg);
                eprintln!("{msg}");
                app.handle().exit(1);
                return Ok(());
            }

            app.manage(AppState {
                skill_root: skill_root.clone(),
            });

            let show_item = MenuItem::with_id(app, "show", "打开 Judy", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出 Judy", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            let _tray = TrayIconBuilder::with_id("main-tray")
                .menu(&menu)
                .tooltip("Judy")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main_window(app),
                    "quit" => request_quit(app),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .build(app)?;

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!("window.location.replace('{UI_URL}');"));
                let _ = window.show();
                let _ = window.set_focus();
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| match event {
            RunEvent::ExitRequested { api, .. } => {
                if app_handle.try_state::<AppState>().is_some()
                    && !QUITTING.load(Ordering::SeqCst)
                {
                    api.prevent_exit();
                    request_quit(&app_handle);
                }
            }
            RunEvent::Exit => {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    stop_all(&state.skill_root);
                }
            }
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => show_main_window(&app_handle),
            _ => {}
        });
}
