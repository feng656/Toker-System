"""部署worker仅一个副本；不在多worker API进程中内嵌调度器。"""
from threading import Event
import signal
from . import config
from .scheduler import start_scheduler, stop_scheduler


def main():
    config.validate()
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    start_scheduler()
    try:
        stop.wait()
    finally:
        stop_scheduler()


if __name__ == '__main__':
    main()
