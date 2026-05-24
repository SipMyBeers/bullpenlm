"""Events — in-process pub/sub fan-out for audit events.

Every call to `publish(bullpen, event)` is mirrored to every subscriber
(SSE connection) for that bullpen. Subscribers get a thread-safe queue
they can drain in a loop and emit `data: <json>\n\n` to their HTTP
response. When the client disconnects (write errors), the handler calls
`unsubscribe()` to free the queue.

This is intentionally a tiny implementation — no Redis, no asyncio.
We're single-process by design (one bullpen host = one Python process),
so an in-memory pub/sub is perfect and survives a server restart by
clients reconnecting + re-rendering from the audit log.
"""
from __future__ import annotations
import json
import queue
import threading
from typing import Optional

_lock = threading.Lock()
# bullpen → list of queues
_subscribers: dict[str, list[queue.Queue]] = {}

# Cap a slow subscriber's backlog so a stuck browser tab can't OOM the host
MAX_QUEUE_DEPTH = 200


def subscribe(bullpen: str) -> queue.Queue:
    """Create a fresh subscription queue. Call unsubscribe(bullpen, q)
    when the client disconnects."""
    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_DEPTH)
    with _lock:
        _subscribers.setdefault(bullpen, []).append(q)
    return q


def unsubscribe(bullpen: str, q: queue.Queue) -> None:
    with _lock:
        lst = _subscribers.get(bullpen) or []
        try: lst.remove(q)
        except ValueError: pass
        if not lst:
            _subscribers.pop(bullpen, None)


def publish(bullpen: str, event: dict) -> int:
    """Push `event` to every active subscriber of `bullpen`.
    Returns the number of subscribers that received it."""
    payload = json.dumps(event, default=str)
    with _lock:
        subs = list(_subscribers.get(bullpen) or [])
    delivered = 0
    for q in subs:
        try:
            q.put_nowait(payload)
            delivered += 1
        except queue.Full:
            # Drop oldest, keep newest — a slow client falls behind
            try: q.get_nowait()
            except queue.Empty: pass
            try: q.put_nowait(payload); delivered += 1
            except queue.Full: pass
    return delivered


def subscriber_count(bullpen: Optional[str] = None) -> int:
    with _lock:
        if bullpen is None:
            return sum(len(v) for v in _subscribers.values())
        return len(_subscribers.get(bullpen) or [])
