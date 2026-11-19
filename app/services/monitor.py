import httpx
import time


def check_api(url: str, method: str = "GET"):
    start_time = time.perf_counter()

    try:
        response = httpx.request(
            method=method,
            url=url,
            timeout=10.0
        )

        response_time = round(
            (time.perf_counter() - start_time) * 1000, 2
        )

        return {
            "status": "UP" if response.is_success else "DOWN",
            "status_code": response.status_code,
            "response_time": response_time
        }

    except httpx.RequestError:
        response_time = round(
            (time.perf_counter() - start_time) * 1000, 2
        )

        return {
            "status": "DOWN",
            "status_code": None,
            "response_time": response_time
        }