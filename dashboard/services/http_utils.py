"""
"진짜" 벽시계 기준 타임아웃이 걸리는 HTTP GET 헬퍼.

requests의 timeout= 옵션은 소켓의 각 개별 읽기(recv)에만 적용된다. 서버가
응답을 아주 느리게 찔끔찔끔 흘려보내면(청크 전송 등) 각 조각은 timeout 안에
들어오기 때문에 전체적으로는 무한정 멈출 수 있다 - 실제 PythonAnywhere
배포에서 DART corpCode.xml 다운로드와 법령 본문 조회(lawService.do) 양쪽에서
이 문제가 재현됐다.

이 헬퍼는 요청을 데몬 스레드에서 실행하고 스레드 자체에 join(timeout=...)을
걸어, 응답이 안 오면 정해진 시간 안에 반드시 제어를 돌려준다. 데몬 스레드라
타임아웃 이후에도 백그라운드에서 계속 매달려 있을 수 있지만(드물게), 메인
프로세스 종료를 막지는 않는다 - 한 번 실행하고 끝나는 스케줄 스크립트에 맞는
동작이다.
"""

import queue
import threading
import time

import requests


class HardTimeoutError(Exception):
    """정해진 시간 안에 응답을 받지 못했을 때 발생한다."""


def _get_once(url, hard_timeout_seconds, **kwargs):
    result_queue: "queue.Queue" = queue.Queue(maxsize=1)

    def _worker():
        try:
            response = requests.get(url, **kwargs)
            result_queue.put(("ok", response))
        except Exception as error:  # noqa: BLE001 - 그대로 호출측에 다시 던짐
            result_queue.put(("error", error))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=hard_timeout_seconds)

    if thread.is_alive():
        raise HardTimeoutError(
            f"{hard_timeout_seconds}초 안에 응답을 받지 못했습니다(서버가 응답을 "
            "느리게 보내고 있을 수 있습니다)."
        )

    status, payload = result_queue.get()
    if status == "error":
        raise payload
    return payload


def get_with_hard_timeout(
    url,
    hard_timeout_seconds,
    retry_attempts=3,
    retry_backoff_seconds=0.1,
    **kwargs,
):
    """GET with a wall-clock timeout and bounded transient-error retries.

    Connection errors, hard timeouts, HTTP 429, and HTTP 5xx responses are
    retried. Other HTTP responses are returned to the caller unchanged.
    """
    attempts = max(1, int(retry_attempts))
    last_error = None
    for attempt in range(attempts):
        try:
            response = _get_once(url, hard_timeout_seconds, **kwargs)
            if response.status_code != 429 and response.status_code < 500:
                return response
            last_error = requests.HTTPError(f"HTTP {response.status_code}")
            if attempt == attempts - 1:
                return response
        except (requests.RequestException, HardTimeoutError) as error:
            last_error = error
            if attempt == attempts - 1:
                raise
        time.sleep(max(0, retry_backoff_seconds) * (2 ** attempt))
    raise last_error
