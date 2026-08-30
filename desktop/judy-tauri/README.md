# Judy 桌面壳（Tauri）

商用包里的 **Judy.app** 源码，口径与灵犀 `desktop/lingxi-tauri` 相同：Tauri 窗口 + `Contents/Resources/python/`（python-build-standalone 3.12）。

版本号在 `tauri build` 前由 `scripts/sync_desktop_version.py` 从仓库根 `VERSION` 写入。

客户文档见 `docs/桌面应用说明.md`、`docs/交付说明.md`。

不要把 `src-tauri/target/**/Judy.app` 直接发给客户：那份通常还没有内嵌 Python。正式包走：

```bash
python scripts/package.py --customer "客户名" --wxid 客户目录名
```
