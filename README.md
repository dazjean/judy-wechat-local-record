# Judy

正式产品名：**Judy**，副标题「本机微信会话分析」。工程目录为 `Judy-wechat-local-record`，发行包名 `Judy`，当前版本 `1.0.0`。

一期：本机微信同步 → 结构化存储 → 规则统计 / AI 诊断 → 页面查看与导出。

客户侧只使用「微信同步」「微信读取初始化」，不出现第三方读取组件名称。客户交付包不含源码，并绑定约定微信系统号。

## 目录

- `backend/` FastAPI + SQLite
- `frontend/` Vue 3 + Element Plus
- `scripts/start.sh` / `start.bat` 开发启动
- `scripts/restart.sh` / `restart.bat` 开发快速重启（先停 8090 再启动）
- `scripts/stop.sh` / `stop.bat` 开发停止（关掉 8090 上的 Judy）
- `scripts/get_wxid.sh` / `get_wxid.bat` 交付前让客户一键读取本机 wxid
- `scripts/package.py` 生产打包（Nuitka + Tauri Judy.app + 微信授权）
- `scripts/issue_license.py` 单独签发授权
- `docs/` 使用说明（客户）、部署说明、交付说明（实施内部）

## 开发启动

```bash
cd Judy-wechat-local-record
cp .env.example .env
./scripts/start.sh
```

会打开 Judy 应用窗口。源码运行默认不校验授权。若只改前端，可另开终端 `cd frontend && npm install && npm run dev`，浏览器打开 `http://127.0.0.1:5173`。

## 客户交付

在**客户同系统**上打包（Windows 客户必须在 Windows 上构建）：

```bash
cd Judy-wechat-local-record
source .venv/bin/activate
python scripts/package.py --customer "客户名" --wxid wxid_客户系统号
```

产出在 `dist-release/`。Mac 正式包是 **Judy.app + 内嵌 Python + Nuitka 模块**（与灵犀商用部署包同一口径）。需要 CPython 3.12、Node、Rust。只把 zip / 文件夹发给客户，不要发源码、`.venv`、`packaging/keys`。细节见 `docs/交付说明.md`。

## 测试

```bash
cd Judy-wechat-local-record/backend
PYTHONPATH=. python -m pytest tests -q
```
