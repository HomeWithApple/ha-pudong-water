"""接口客户端：用假的 HTTP 会话，不联网。"""

from __future__ import annotations

from datetime import date
import json

import pytest

from custom_components.pudong_water.api import ApiError, InvalidAccount, PudongWaterClient

from .conftest import BILLS, CID


class FakeResp:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, status, text):
        self.status, self.text = status, text
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResp(self.status, self.text)


async def test_ok_parses_data_string():
    body = json.dumps({"cid": CID, "code": "1", "dz": "x", "data": json.dumps(BILLS)})
    s = FakeSession(200, body)
    bills = await PudongWaterClient(s, CID).bills(date(2026, 11, 5))
    assert len(bills) == 4
    url, params, headers = s.calls[0]
    assert params == {"cid": CID, "kaishisj": "2025-10", "jieshusj": ""}
    assert "MicroMessenger" in headers["User-Agent"]


@pytest.mark.parametrize(
    ("status", "text", "exc"),
    [
        (200, json.dumps({"code": "0", "data": ""}), InvalidAccount),
        (500, "", ApiError),
        (200, "<html>维护中</html>", ApiError),
        (200, json.dumps({"code": "1", "data": "{bad"}), ApiError),
    ],
)
async def test_errors(status, text, exc):
    with pytest.raises(exc):
        await PudongWaterClient(FakeSession(status, text), CID).bills()


async def test_empty_data_string_is_empty_list():
    body = json.dumps({"code": "1", "data": ""})
    assert await PudongWaterClient(FakeSession(200, body), CID).bills() == []
