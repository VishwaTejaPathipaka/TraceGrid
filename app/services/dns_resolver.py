import json
from pathlib import Path
import socket
import subprocess
import sys
from threading import BoundedSemaphore
from time import monotonic


_RESOLVER_SLOTS = BoundedSemaphore(8)
_RESOLVER_SCRIPT = str(Path(__file__).resolve())


def is_missing_hostname(error: socket.gaierror) -> bool:
    return error.errno in {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}


def remaining_time(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Monitoring deadline exceeded")
    return remaining


def lookup_host(host: str, port: int, deadline: float) -> list[tuple[int, tuple]]:
    if not _RESOLVER_SLOTS.acquire(timeout=remaining_time(deadline)):
        raise TimeoutError("Monitoring DNS lookup timed out")

    try:
        remaining_time(deadline)
        # System getaddrinfo cannot be cancelled in a thread. A timed-out child can be reaped.
        with subprocess.Popen(
            [sys.executable, "-I", "-S", _RESOLVER_SCRIPT, host, str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as process:
            try:
                output, _ = process.communicate(timeout=remaining_time(deadline))
            except (TimeoutError, subprocess.TimeoutExpired) as error:
                process.kill()
                raise TimeoutError("Monitoring DNS lookup timed out") from error

        remaining_time(deadline)
        if process.returncode != 0:
            raise OSError("The monitoring resolver process failed")
        result = json.loads(output)
        if isinstance(result, dict):
            raise socket.gaierror(result["error"], "The monitoring hostname could not be resolved")
        return [(family, tuple(sockaddr)) for family, sockaddr in result]
    finally:
        _RESOLVER_SLOTS.release()


if __name__ == "__main__":
    try:
        answers = socket.getaddrinfo(
            sys.argv[1], int(sys.argv[2]), socket.AF_UNSPEC, socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
    except socket.gaierror as error:
        print(json.dumps({"error": error.errno}))
    else:
        print(json.dumps([(family, sockaddr) for family, _, _, _, sockaddr in answers]))
