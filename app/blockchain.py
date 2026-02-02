import json
import hashlib
from time import time
from urllib.parse import urlparse
from threading import RLock
import requests


class Blockchain:
    """
    Core Blockchain implementation with:
    - Proof of Work (PoW)
    - Chain validation / basic longest-chain consensus
    - Fast file-hash indexing for verification endpoints
    - Timestamp precision normalization for stable hashing
    - Each block persistently stores its own `hash`
    """

    def __init__(self):
        self.current_transactions = []
        self.chain = []
        self.nodes = set()
        self.lock = RLock()

        # Fast lookup indexes for file authenticity
        self.file_hashes = set()  # Set[str]
        self.filename_to_hashes = {}  # Dict[str, Set[str]]

        # Genesis block
        self.new_block(previous_hash="1", proof=100)

    # ---------------------------
    # Indexing helpers
    # ---------------------------
    def _index_transactions(self, transactions):
        """Update in-memory indexes from a list of tx dicts."""
        for tx in transactions or []:
            if isinstance(tx, dict):
                fh = tx.get("file_hash")
                fn = tx.get("filename")
                if fh:
                    self.file_hashes.add(fh)
                if fn and fh:
                    self.filename_to_hashes.setdefault(fn, set()).add(fh)

    def _rebuild_indexes(self):
        """Rebuild all indexes from scratch (used after chain replacement)."""
        self.file_hashes.clear()
        self.filename_to_hashes.clear()
        for block in self.chain:
            self._index_transactions(block.get("transactions", []))
        self._index_transactions(self.current_transactions)

    def replace_chain_and_reindex(self, chain):
        """
        Replace the current chain with given chain (list of blocks) and rebuild indexes.
        Assumes 'chain' is already validated by the caller (or remote consensus).
        """
        if not isinstance(chain, list):
            raise ValueError("replace_chain_and_reindex expects a list of blocks")
        with self.lock:
            self.chain = chain
            self.current_transactions = []
            self._rebuild_indexes()

    # ---------------------------
    # Node registration
    # ---------------------------
    def register_node(self, address):
        """Add a new node to the network from 'http://host:port' or 'host:port'."""
        parsed_url = urlparse(address)
        if parsed_url.netloc:
            self.nodes.add(parsed_url.netloc)
        elif parsed_url.path:
            self.nodes.add(parsed_url.path)
        else:
            raise ValueError("Invalid URL")

    # ---------------------------
    # Chain validation
    # ---------------------------
    def valid_chain(self, chain):
        """Check if a blockchain is valid (prev-hash linkage + PoW)."""
        if not chain:
            return False

        last_block = chain[0]
        current_index = 1

        while current_index < len(chain):
            block = chain[current_index]

            # Recompute the hash of the last block (ignoring any stored 'hash')
            last_block_hash = self.hash(last_block)

            # Verify previous hash linkage
            if block.get("previous_hash") != last_block_hash:
                return False

            # Verify Proof of Work
            if not self.valid_proof(
                last_block.get("proof"), block.get("proof"), last_block_hash
            ):
                return False

            last_block = block
            current_index += 1

        return True

    # ---------------------------
    # Consensus algorithm
    # ---------------------------
    def resolve_conflicts(self, timeout=2):
        """
        Replaces our chain with the longest valid chain in the network.
        Accepts either:
          - GET /chain -> [ ...blocks... ]
          - GET /chain -> { "length": N, "chain": [ ...blocks... ] }
        """
        neighbours = self.nodes
        new_chain = None
        max_length = len(self.chain)

        for node in neighbours:
            try:
                response = requests.get(f"http://{node}/chain", timeout=timeout)
            except requests.exceptions.RequestException:
                continue

            if response.status_code != 200:
                continue

            try:
                data = response.json()
            except ValueError:
                continue

            # Normalize shape
            if isinstance(data, list):
                length = len(data)
                chain = data
            elif isinstance(data, dict):
                chain = data.get("chain")
                length = (
                    data.get("length")
                    if isinstance(data.get("length"), int)
                    else (len(chain) if isinstance(chain, list) else None)
                )
            else:
                chain, length = None, None

            if not isinstance(chain, list) or not isinstance(length, int):
                continue

            if length > max_length and self.valid_chain(chain):
                max_length = length
                new_chain = chain

        if new_chain:
            self.replace_chain_and_reindex(new_chain)
            return True
        return False

    # ---------------------------
    # Block and transaction creation
    # ---------------------------
    def new_block(self, proof, previous_hash=None):
        """
        Create a new block, compute & store its hash, append to chain, and
        index its transactions.
        """
        with self.lock:
            block = {
                "index": len(self.chain) + 1,
                "timestamp": round(time(), 6),  # normalize precision for stable hashing
                "transactions": self.current_transactions,
                "proof": proof,
                "previous_hash": previous_hash
                or (self.hash(self.chain[-1]) if self.chain else "1"),
            }

            # Compute the block hash (excluding the 'hash' field itself)
            block_hash = self.hash(block)
            block["hash"] = block_hash

            # Index current transactions before resetting
            self._index_transactions(self.current_transactions)

            # Reset the transaction list
            self.current_transactions = []

            # Append to chain
            self.chain.append(block)
            return block

    def new_transaction(self, sender, recipient, amount):
        """Create a new payment transaction for the next mined block."""
        with self.lock:
            self.current_transactions.append(
                {"sender": sender, "recipient": recipient, "amount": amount}
            )
            return self.last_block["index"] + 1

    def add_resume_auth_tx(
        self, *, candidate, filename, file_hash, verified_by, note=None
    ):
        """
        Create a resume authenticity transaction structure.
        """
        tx = {
            "type": "resume_proof",
            "candidate": candidate,
            "filename": filename,
            "file_hash": file_hash,
            "verified_by": verified_by,
            "note": note,
            "ts": round(time(), 6),
        }
        with self.lock:
            self.current_transactions.append(tx)
            return self.last_block["index"] + 1

    @property
    def last_block(self):
        return self.chain[-1]

    # ---------------------------
    # Hashing and proof of work
    # ---------------------------
    @staticmethod
    def hash(block):
        """
        Generate SHA-256 hash of a block with normalized timestamp precision.
        Ensures the 'hash' field (if present) is ignored when computing.
        """
        block_copy = dict(block)
        # Normalize timestamp precision for consistency
        if "timestamp" in block_copy:
            block_copy["timestamp"] = round(block_copy["timestamp"], 6)
        # Exclude the stored hash from the hash computation
        block_copy.pop("hash", None)

        block_string = json.dumps(
            block_copy,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self, last_block):
        """Simple Proof of Work."""
        last_proof = last_block["proof"]
        last_hash = self.hash(last_block)
        proof = 0
        while not self.valid_proof(last_proof, proof, last_hash):
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof, last_hash, difficulty=4):
        """
        Validates the proof: Does hash(last_proof, proof, last_hash) start with N zeros?
        """
        guess = f"{last_proof}{proof}{last_hash}".encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:difficulty] == "0" * difficulty

    # ---------------------------
    # Convenience helpers
    # ---------------------------
    def has_file_hash(self, file_hash: str) -> bool:
        """Fast check if a file hash has ever been recorded on-chain."""
        return file_hash in self.file_hashes

    def get_chain_payload(self):
        """
        Optional helper for APIs: return a standardized payload that includes length.
        """
        return {
            "length": len(self.chain),
            "chain": self.chain,
        }
