from uuid import uuid4
from flask import Flask
from flask_cors import CORS
import os

from app.config import Config
from app.blockchain import Blockchain
from app.miner import Miner
from app.routes import create_blueprint
from app.storage import load_chain


def create_app():
    app = Flask(__name__, static_folder="static")
    app.config.from_object(Config)
    CORS(app)

    # ---------------------------------------------------------------------
    # Ensure required folders exist
    # ---------------------------------------------------------------------
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.dirname(app.config["DATA_FILE"]), exist_ok=True)

    # Create verify-temp folder to avoid overwriting during verification
    verify_temp = os.path.join(app.config["UPLOAD_FOLDER"], "_verify_temp")
    os.makedirs(verify_temp, exist_ok=True)

    # ---------------------------------------------------------------------
    # Core blockchain + miner initialization
    # ---------------------------------------------------------------------
    blockchain = Blockchain()

    # Load persisted chain if available
    loaded_chain = load_chain(app.config["DATA_FILE"])
    if loaded_chain and blockchain.valid_chain(loaded_chain):
        blockchain.replace_chain_and_reindex(loaded_chain)

    node_identifier = str(uuid4()).replace("-", "")
    miner = Miner(
        blockchain=blockchain, node_identifier=node_identifier, interval_sec=5
    )

    # ---------------------------------------------------------------------
    # Register API routes via blueprint
    # ---------------------------------------------------------------------
    bp = create_blueprint(
        blockchain=blockchain,
        miner=miner,
        node_identifier=node_identifier,
        upload_folder=app.config["UPLOAD_FOLDER"],
        data_file=app.config["DATA_FILE"],
        max_file_mb=app.config["MAX_FILE_MB"],
    )
    app.register_blueprint(bp)

    # ---------------------------------------------------------------------
    # Serve front-end (web UI)
    # ---------------------------------------------------------------------
    @app.route("/")
    def homepage():
        """
        Serves the static web UI (index.html) for file upload/verification.
        """
        return app.send_static_file("index.html")

    return app


# -------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000)
