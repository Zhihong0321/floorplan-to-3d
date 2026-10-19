"""Small network helper: retries with backoff for flaky connections, clear errors. Stdlib only."""
import socket
import time
import urllib.error
import urllib.request

RETRY_CODES = {408, 425, 429, 500, 502, 503, 504}


def open_with_retries(req, timeout=40, tries=3, base_delay=1.5):
    """urllib.request.urlopen with retries on timeouts, connection errors and 429/5xx. Other HTTP errors raise at once."""
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or i == tries - 1:
                raise
            last = e
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            last = e
            if i == tries - 1:
                raise
        time.sleep(base_delay * (2 ** i))
    raise last  # pragma: no cover
