from threading import Barrier, Lock


class CountingBarrier(Barrier):
    """A two-party Barrier that records arrivals.

    A race test asserts `hits == parties` at the end: if the hook that calls `wait`
    stops being reached (renamed or no longer called), the Barrier never trips and
    the test would otherwise pass by luck of scheduling.
    """

    def __init__(self, parties: int = 2) -> None:
        super().__init__(parties)
        self.hits = 0
        self._hits_lock = Lock()

    def wait(self, timeout: float | None = None) -> int:
        with self._hits_lock:
            self.hits += 1
        return super().wait(timeout)
