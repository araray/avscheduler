from flask import Flask, render_template, redirect
import sqlite3
import toml

scheduler = None

def get_scheduler_instance():
    global scheduler
    if scheduler is None:
        from scheduler import scheduler  # Late import
    return scheduler


app = Flask(__name__)
CONFIG = toml.load("config.toml")
DB_PATH = CONFIG["settings"]["db_path"]

@app.route("/")
def index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Fetch jobs and their latest logs
    cursor.execute("SELECT DISTINCT job_id FROM job_execution_logs")
    jobs = []
    for row in cursor.fetchall():
        job_id = row[0]
        cursor.execute(
            """
            SELECT timestamp, exit_code, execution_time
            FROM job_execution_logs
            WHERE job_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (job_id,),
        )
        log = cursor.fetchone()
        last_execution = log[0] if log else "N/A"
        last_exit_code = log[1] if log else "N/A"
        last_execution_time = log[2] if log else "N/A"

        # Fetch the next execution time from APScheduler
        apscheduler_job = get_scheduler_instance().get_job(job_id)
        next_execution = apscheduler_job.next_run_time if apscheduler_job else "N/A"

        jobs.append({
            "id": job_id,
            "last_execution": last_execution,
            "last_exit_code": last_exit_code,
            "last_execution_time": last_execution_time,
            "next_execution": next_execution,
            "condition": CONFIG["jobs"].get(job_id, {}).get("condition", "N/A"),
        })
    conn.close()

    return render_template("index.html", jobs=jobs)


@app.route("/job/<job_id>")
def job_details(job_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Fetch execution logs for the selected job
    cursor.execute(
        """
        SELECT timestamp, exit_code, execution_time
        FROM job_execution_logs
        WHERE job_id = ?
        ORDER BY timestamp DESC
        """,
        (job_id,),
    )
    logs = cursor.fetchall()
    conn.close()

    return render_template("job_details.html", job_id=job_id, logs=logs)



@app.route("/delete_logs/<job_id>")
def delete_logs(job_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM job_execution_logs WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()
    return redirect("/")


if __name__ == "__main__":
    # Read host and port from config file
    host = CONFIG["web_server"].get("host", "127.0.0.1")
    port = CONFIG["web_server"].get("port", 5000)

    # Run the Flask app
    app.run(host=host, port=port, debug=False)
