"""A chain has at most 10 HTTP/model requests and 100s wall time; no retry storm."""
import time
from contextvars import ContextVar
from contextlib import contextmanager
_current=ContextVar('outreach_chain',default=None)
@contextmanager
def chain(seconds=100,calls=10):
    if _current.get() is not None:
        yield;return
    token=_current.set({'deadline':time.monotonic()+seconds,'calls':calls})
    try:yield
    finally:_current.reset(token)
def checkpoint(request=False):
    v=_current.get()
    if not v:return 100
    remaining=v['deadline']-time.monotonic()
    if remaining<=0:raise TimeoutError('Generation chain deadline exceeded')
    if request:
        if v['calls']<=0:raise TimeoutError('Generation chain request limit exceeded')
        v['calls']-=1
    return remaining
