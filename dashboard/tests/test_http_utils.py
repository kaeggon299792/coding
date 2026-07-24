"""
http_utils.get_with_hard_timeout 검증.

실제 PythonAnywhere 배포에서 DART corpCode.xml, 법령 본문 조회(lawService.do)
양쪽에서 "requests의 timeout이 걸렸는데도 응답이 안 옴(청크 단위로 아주 느리게
내려오는 서버)" 문제가 재현됐다. 이 테스트는 그 상황(느린 requests.get)에서도
정해진 시간 안에 반드시 제어가 돌아오는지 확인한다.
"""

import time

import pytest

from services.http_utils import HardTimeoutError, get_with_hard_timeout


def test_returns_response_when_fast_enough(monkeypatch):
    class FakeResponse:
        status_code = 200

    monkeypatch.setattr("requests.get", lambda url, **kwargs: FakeResponse())

    response = get_with_hard_timeout("https://example.com", hard_timeout_seconds=2)
    assert response.status_code == 200


def test_raises_hard_timeout_when_requests_hangs(monkeypatch):
    def _hanging_get(url, **kwargs):
        time.sleep(5)  # 하드 타임아웃(0.3초)보다 훨씬 오래 걸리는 상황을 흉내낸다
        raise AssertionError("여기까지 오면 안 됨(테스트가 5초를 기다려야 하므로)")

    monkeypatch.setattr("requests.get", _hanging_get)

    start = time.monotonic()
    with pytest.raises(HardTimeoutError):
        get_with_hard_timeout("https://example.com", hard_timeout_seconds=0.3)
    elapsed = time.monotonic() - start

    assert elapsed < 2, "하드 타임아웃이 실제로는 훨씬 오래 걸렸습니다(고쳐지지 않음)"


def test_reraises_original_exception_when_request_fails_fast(monkeypatch):
    import requests

    def _failing_get(url, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("requests.get", _failing_get)

    with pytest.raises(requests.ConnectionError):
        get_with_hard_timeout("https://example.com", hard_timeout_seconds=2)
