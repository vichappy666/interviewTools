"""跨模块共享的 HTTP 请求工具。"""
from fastapi import Request


def client_ip(request: Request) -> str:
    """从 Request 抽出客户端 IP，优先信任 ``X-Forwarded-For`` 第一项。

    历史上这段逻辑在 auth / admin / recharge 三处复制，统一在此。
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
