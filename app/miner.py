from threading import Thread, Event, Lock
import time


class Miner:
    """
    Thread-safe auto-miner.
    - start()/stop() are idempotent
    - interval_sec controls time between blocks
    """

    def __init__(self, blockchain, node_identifier, interval_sec=5):
        self.blockchain = blockchain
        self.node_identifier = node_identifier
        self.interval_sec = interval_sec

        self._lock = Lock()
        self._stop_event = Event()
        self._thread = None

    def is_active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_active():
                return False
            self._stop_event.clear()
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            if not self.is_active():
                return False
            self._stop_event.set()
            return True

    def _run(self):
        while not self._stop_event.is_set():
            with self.blockchain.lock:
                last_block = self.blockchain.last_block
                proof = self.blockchain.proof_of_work(last_block)

                # Reward miner
                self.blockchain.new_transaction(
                    sender="0", recipient=self.node_identifier, amount=1
                )

                previous_hash = self.blockchain.hash(last_block)
                self.blockchain.new_block(proof, previous_hash)

            # Sleep between blocks
            time.sleep(self.interval_sec)
