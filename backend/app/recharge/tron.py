"""TronGrid 同步 HTTP 客户端（M3 T3）。

用 httpx.Client 包一层，给 verifier 提供 3 个查询能力：
- get_transaction_info(tx_hash)：交易回执（包含 receipt/blockNumber/contract_address 等）
- get_transaction(tx_hash)：交易体（包含 raw_data.contract.parameter.value，含 owner_address/data）
- get_now_block_number()：当前最新区块号（用于算确认数）

T3 阶段所有测试都 mock 这个 client，不发真实网络请求；T10 才在 Shasta 端到端跑。
"""
from __future__ import annotations

from typing import Any

import httpx


class TronClient:
    """TronGrid API 客户端（同步）。"""

    MAINNET_BASE = "https://api.trongrid.io"
    SHASTA_BASE = "https://api.shasta.trongrid.io"

    def __init__(
        self,
        network: str = "shasta",
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        base = self.MAINNET_BASE if network == "mainnet" else self.SHASTA_BASE
        headers: dict[str, str] = {}
        if api_key:
            headers["TRON-PRO-API-KEY"] = api_key
        self.network = network
        self._client = httpx.Client(base_url=base, headers=headers, timeout=timeout)

    def get_transaction_info(self, tx_hash: str) -> dict[str, Any]:
        """POST /wallet/gettransactioninfobyid

        返回结构（成功时）大致：
        {
            "id": "<tx_hash>",
            "blockNumber": 12345,
            "blockTimeStamp": 1700000000000,  # ms
            "contract_address": "41...",       # hex 41+20B
            "receipt": {"result": "SUCCESS", ...},
            ...
        }
        交易不存在时通常返回 {}（空 dict）。
        """
        r = self._client.post(
            "/wallet/gettransactioninfobyid", json={"value": tx_hash}
        )
        r.raise_for_status()
        return r.json()

    def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        """POST /wallet/gettransactionbyid

        返回结构包含：
        {
            "txID": "...",
            "raw_data": {
                "contract": [
                    {
                        "type": "TriggerSmartContract",
                        "parameter": {
                            "value": {
                                "owner_address": "41...",
                                "contract_address": "41...",
                                "data": "a9059cbb000...",  # transfer(address,uint256) 调用
                            },
                            ...
                        },
                    }
                ],
                ...
            },
            ...
        }
        """
        r = self._client.post("/wallet/gettransactionbyid", json={"value": tx_hash})
        r.raise_for_status()
        return r.json()

    def get_now_block_number(self) -> int:
        """POST /wallet/getnowblock，返回当前最新区块号。"""
        r = self._client.post("/wallet/getnowblock")
        r.raise_for_status()
        data = r.json()
        return int(data["block_header"]["raw_data"]["number"])

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TronClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
