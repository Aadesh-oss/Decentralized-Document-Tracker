import tempfile

from app.blockchain import Blockchain
from app.file_hashing import hash_file


class BlockchainTestHarness(Blockchain):
    @staticmethod
    def valid_proof(last_proof, proof, last_hash, difficulty=2):
        return super(BlockchainTestHarness, BlockchainTestHarness).valid_proof(
            last_proof, proof, last_hash, difficulty=difficulty
        )


def test_valid_chain_and_tamper():
    bc = BlockchainTestHarness()

    # Block 1
    bc.new_transaction("a", "b", 1)
    proof1 = bc.proof_of_work(bc.last_block)
    bc.new_block(proof1, bc.hash(bc.last_block))

    # Block 2
    bc.new_transaction("c", "d", 2)
    proof2 = bc.proof_of_work(bc.last_block)
    bc.new_block(proof2, bc.hash(bc.last_block))

    assert bc.valid_chain(bc.chain)

    # Tamper with first real block
    bc.chain[1]["transactions"][0]["amount"] = 999
    assert not bc.valid_chain(bc.chain)


def test_hash_file_matches_known_value():
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"hello world")
        tmp.flush()
        assert (
            hash_file(tmp.name)
            == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )
