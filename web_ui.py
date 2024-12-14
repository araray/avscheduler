from flask import Flask, render_template
import sqlite3
import toml

# Load configuration
CONFIG = toml.load("config.toml")

# Flask app initialization
app = Flask(__name__)

DB_PATH = CONFIG["settings"]["db_path"]

@app.route("/")
def index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Fetch job logs
    cursor.execute("SELECT * FROM job_execution_logs ORDER BY timestamp DESC")
    logs = cursor.fetchall()
    conn.close()

    return render_template("index.html", logs=logs)

if __name__ == "__main__":
    # Read host and port from config file
    host = CONFIG["web_server"].get("host", "127.0.0.1")
    port = CONFIG["web_server"].get("port", 5000)

    # Run the Flask app
    app.run(host=host, port=port, debug=False)
