import os
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from app.file_hashing import hash_file
from app.storage import save_chain

# Accepted MIME prefixes for uploads
ALLOWED_MIME_PREFIXES = {
    "application/pdf",
    "image/",
    "text/",
    "application/msword",
    "application/vnd",
}


def _within_size_limit(stream_len, max_mb):
    return stream_len is None or stream_len <= max_mb * 1024 * 1024


def _allowed_mime(mimetype):
    if not mimetype:
        return True  # allow unknown for demo
    return any(mimetype.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)


def create_blueprint(
    blockchain, miner, node_identifier, upload_folder, data_file, max_file_mb
):
    bp = Blueprint("trustnet", __name__)

    # Helper to save chain to disk
    def persist_chain():
        save_chain(data_file, blockchain.chain)

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------
    @bp.route("/status", methods=["GET"])
    def status():
        return jsonify(
            {
                "mining_active": miner.is_active(),
                "chain_length": len(blockchain.chain),
                "nodes": list(blockchain.nodes),
            }
        ), 200

    # ---------------------------------------------------------
    # MINING
    # ---------------------------------------------------------
    @bp.route("/mine", methods=["GET"])
    def mine():
        with blockchain.lock:
            last_block = blockchain.last_block
            proof = blockchain.proof_of_work(last_block)

            blockchain.new_transaction(sender="0", recipient=node_identifier, amount=1)
            previous_hash = blockchain.hash(last_block)
            block = blockchain.new_block(proof, previous_hash)
            persist_chain()

        return jsonify(
            {
                "message": "New Block Forged",
                "index": block["index"],
                "transactions": block["transactions"],
                "proof": block["proof"],
                "previous_hash": block["previous_hash"],
            }
        ), 200

    @bp.route("/mine/auto", methods=["POST"])
    def auto_mine():
        payload = request.get_json() or {}
        active = payload.get("active", None)
        if active is None:
            return jsonify({"error": "Missing 'active' field (true/false)"}), 400

        if active:
            started = miner.start()
            msg = "Auto-mining started" if started else "Already mining"
            return jsonify({"message": msg}), 200
        else:
            stopped = miner.stop()
            msg = "Auto-mining stopped" if stopped else "Mining already stopped"
            return jsonify({"message": msg}), 200

    # ---------------------------------------------------------
    # TRANSACTIONS
    # ---------------------------------------------------------
    @bp.route("/transactions/new", methods=["POST"])
    def new_transaction():
        values = request.get_json()
        if not values:
            return jsonify({"error": "Invalid JSON body"}), 400

        required = ["sender", "recipient", "amount"]
        if not all(k in values for k in required):
            return jsonify({"error": "Missing values"}), 400

        index = blockchain.new_transaction(
            values["sender"], values["recipient"], values["amount"]
        )
        return jsonify({"message": f"Transaction will be added to Block {index}"}), 201

    # ---------------------------------------------------------
    # FULL CHAIN
    # ---------------------------------------------------------
    @bp.route("/chain", methods=["GET"])
    def full_chain():
        return jsonify(
            {"chain": blockchain.chain, "length": len(blockchain.chain)}
        ), 200

    # ---------------------------------------------------------
    # NODES & CONSENSUS
    # ---------------------------------------------------------
    @bp.route("/nodes/register", methods=["POST"])
    def register_nodes():
        values = request.get_json()
        if not values or "nodes" not in values:
            return jsonify({"error": "Please supply a valid list of nodes"}), 400

        nodes = values["nodes"]
        if not isinstance(nodes, list):
            return jsonify({"error": "Nodes must be a list"}), 400

        for node in nodes:
            blockchain.register_node(node)

        return jsonify(
            {"message": "New nodes added", "total_nodes": list(blockchain.nodes)}
        ), 201

    @bp.route("/nodes/resolve", methods=["GET"])
    def consensus():
        replaced = blockchain.resolve_conflicts(timeout=2)
        if replaced:
            persist_chain()
            response = {
                "message": "Our chain was replaced",
                "new_chain": blockchain.chain,
            }
        else:
            response = {
                "message": "Our chain is authoritative",
                "chain": blockchain.chain,
            }
        return jsonify(response), 200

    # ---------------------------------------------------------
    # FILE UPLOAD (AUTHENTICITY REGISTRATION)
    # ---------------------------------------------------------
    @bp.route("/file/upload", methods=["POST"])
    def upload_file():
        # Check content length
        cl = request.content_length
        if not _within_size_limit(cl, max_file_mb):
            return jsonify({"error": f"File too large. Max {max_file_mb} MB"}), 413

        if "file" not in request.files:
            return jsonify({"error": "No file part in the request"}), 400

        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not _allowed_mime(file.mimetype):
            return jsonify({"error": f"Disallowed file type: {file.mimetype}"}), 415

        filename = secure_filename(file.filename)
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)

        try:
            file.save(filepath)
        except Exception as e:
            return jsonify({"error": f"Failed to save file: {e}"}), 500

        file_hash = hash_file(filepath)

        candidate = request.form.get("candidate")
        note = request.form.get("note")
        verified_by = request.form.get("verified_by", "TrustNet")

        # Custom resume authenticity transaction
        with blockchain.lock:
            if candidate:
                blockchain.add_resume_auth_tx(
                    candidate=candidate,
                    filename=filename,
                    file_hash=file_hash,
                    verified_by=verified_by,
                    note=note,
                )
            else:
                blockchain.current_transactions.append(
                    {"filename": filename, "file_hash": file_hash, "verified": True}
                )

            # Mine block immediately to record
            last_block = blockchain.last_block
            proof = blockchain.proof_of_work(last_block)
            blockchain.new_transaction(sender="0", recipient=node_identifier, amount=1)
            previous_hash = blockchain.hash(last_block)
            block = blockchain.new_block(proof, previous_hash)

            persist_chain()

        return jsonify(
            {
                "message": "File successfully added to blockchain authenticity ledger.",
                "filename": filename,
                "file_hash": file_hash,
                "block_index": block["index"],
            }
        ), 201

    # ---------------------------------------------------------
    # FILE VERIFY (SAFE TEMP FOLDER VERSION)
    # ---------------------------------------------------------
    @bp.route("/file/verify", methods=["POST"])
    def verify_file():
        # Check content length
        cl = request.content_length
        if not _within_size_limit(cl, max_file_mb):
            return jsonify({"error": f"File too large. Max {max_file_mb} MB"}), 413

        if "file" not in request.files:
            return jsonify({"error": "No file part in the request"}), 400

        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        filename = secure_filename(file.filename)
        verify_folder = os.path.join(upload_folder, "_verify_temp")

        try:
            os.makedirs(verify_folder, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"Failed to create temp folder: {e}"}), 500

        temp_path = os.path.join(verify_folder, filename)
        try:
            file.save(temp_path)
        except Exception as e:
            return jsonify({"error": f"Error saving uploaded file: {e}"}), 500

        # Generate hash and clean up
        try:
            file_hash = hash_file(temp_path)
        except Exception as e:
            return jsonify({"error": f"Failed to hash file: {e}"}), 500
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

        with blockchain.lock:
            # Fast lookup: file hash exists
            if file_hash in blockchain.file_hashes:
                found_block = None
                for block in blockchain.chain:
                    for tx in block.get("transactions", []):
                        if isinstance(tx, dict) and tx.get("file_hash") == file_hash:
                            found_block = block["index"]
                            break
                    if found_block:
                        break
                return jsonify(
                    {
                        "filename": filename,
                        "verified": True,
                        "result": "original document",
                        "block_index": found_block,
                        "message": "File hash found on blockchain (original).",
                    }
                ), 200

            # Filename exists but hash differs
            known_hashes = blockchain.filename_to_hashes.get(filename, set())
            if known_hashes and file_hash not in known_hashes:
                return jsonify(
                    {
                        "filename": filename,
                        "verified": False,
                        "result": "tampered document",
                        "message": "File with same name exists on blockchain but hash differs (tampered).",
                    }
                ), 200

            # Check pending transactions
            for tx in blockchain.current_transactions:
                if isinstance(tx, dict):
                    if tx.get("filename") == filename and tx.get("file_hash") == file_hash:
                        return jsonify(
                            {
                                "filename": filename,
                                "verified": True,
                                "result": "original document",
                                "block_index": blockchain.last_block["index"] + 1,
                                "message": "File found in pending transactions (will be recorded in next block).",
                            }
                        ), 200

        # Not found
        return jsonify(
            {
                "filename": filename,
                "verified": False,
                "result": "tampered document",
                "message": "File not found on blockchain. It may be tampered or not previously recorded.",
            }
        ), 404

    return bp
