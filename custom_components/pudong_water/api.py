"""浦东威立雅水费账单接口。不依赖 Home Assistant，便于单独测试。

这是「浦东威立雅」微信公众号查账单时用的接口：只凭销根号（户号）查询，不用登录。
因此请求以微信内置浏览器的身份发出。只读，不调用缴费或任何提交接口。

注意：只凭户号就能查到账单，返回里还带户名和地址。本集成不保存、不显示这两项。
"""

from __future__ import annotations

from datetime import date
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BILL_URL = "https://mtu.pudongwater.com/wkf/WX/GetBill"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.47"
)
RC_OK = "1"


class PudongWaterError(Exception):
    """所有错误的基类。"""


class InvalidAccount(PudongWaterError):
    """接口不认这个户号（或接口改了）。"""


class ApiError(PudongWaterError):
    """连不上，或返回了意料之外的内容。"""


def start_month(today: date, months_back: int = 13) -> str:
    """查询起始年月。接口实测只回最近一年左右（6 期），多给也没用。"""
    total = today.year * 12 + (today.month - 1) - months_back
    return f"{total // 12}-{total % 12 + 1:02d}"


class PudongWaterClient:
    def __init__(self, session: aiohttp.ClientSession, cid: str, *, timeout: float = 30) -> None:
        self._session = session
        self._cid = cid
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def bills(self, today: date | None = None) -> list[dict[str, Any]]:
        params = {"cid": self._cid, "kaishisj": start_month(today or date.today()), "jieshusj": ""}
        try:
            async with self._session.get(
                BILL_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    raise ApiError(f"账单接口返回 HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ApiError(f"连不上账单接口：{type(err).__name__}") from err
        try:
            body = json.loads(text)
        except ValueError as err:
            raise ApiError("账单接口返回的不是 JSON") from err
        if not isinstance(body, dict):
            raise ApiError("账单接口返回的不是 JSON 对象")
        if str(body.get("code")) != RC_OK:
            raise InvalidAccount(f"账单接口结果码 {body.get('code')}")
        data = body.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data) if data.strip() else []
            except ValueError as err:
                raise ApiError("账单数据不是 JSON") from err
        if not isinstance(data, list):
            raise ApiError("账单数据不是列表")
        return [b for b in data if isinstance(b, dict)]
