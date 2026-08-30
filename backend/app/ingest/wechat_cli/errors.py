from __future__ import annotations


class ReaderError(Exception):
    """内部读取异常，带对外中文文案。"""

    def __init__(self, public_message: str, code: str = "reader_error"):
        super().__init__(public_message)
        self.public_message = public_message
        self.code = code


def map_failure(kind: str, detail: str = "") -> ReaderError:
    table = {
        "not_found": ("微信读取组件未就绪，请重新安装本系统", "reader_missing"),
        "not_inited": ("尚未完成微信读取初始化，或当前微信版本不兼容", "reader_not_ready"),
        "wechat_down": ("请先打开并登录微信，再点同步", "wechat_not_running"),
        "timeout": ("读取超时，请稍后重试", "reader_timeout"),
        "lock_timeout": ("读取繁忙，请稍后重试", "reader_busy"),
        "parse": ("读取结果无法解析，请稍后重试", "reader_parse"),
        "no_session": ("该会话暂无记录或名称无法匹配", "no_history"),
    }
    msg, code = table.get(kind, ("微信读取失败，请稍后重试", "reader_error"))
    return ReaderError(msg, code)
