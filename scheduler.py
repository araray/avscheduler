import os
import toml
import logging
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from subprocess import Popen, PIPE
from models import init_db
from condition_parser import evaluate_condition
import web_ui
from daemon import DaemonContext

from utils import get_valid_directory

# Initialize logging
logs_path = get_valid_directory()
LOG_FILE = os.path.join(str(logs_path), "logs", "scheduler.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Global variables
scheduler = BackgroundScheduler()
CONFIG = {}

# Load configuration
def load_config(config_file="config.toml"):
    """
    Load the configuration file. Return a valid configuration or raise an error if not found.
    """
    global CONFIG
    if os.path.exists(config_file):
        CONFIG = toml.load(config_file)

        # Validate required keys in the configuration
        if "settings" not in CONFIG:
            CONFIG["settings"] = {}

        # Set a default database path if not specified
        if "db_path" not in CONFIG["settings"]:
            CONFIG["settings"]["db_path"] = "jobs.db"

        return CONFIG
    else:
        raise FileNotFoundError(f"Configuration file '{config_file}' not found.")


def write_pid(pid_file):
    """
    Write the current process PID to a PID file.
    """
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    logging.info(f"Daemon PID {os.getpid()} written to {pid_file}.")


def remove_pid(pid_file):
    """
    Remove the PID file.
    """
    if os.path.exists(pid_file):
        os.remove(pid_file)
        logging.info(f"PID file {pid_file} removed.")


# Job Execution
def run_job(job_id, interpreter, command, env_file=None):
    """
    Execute the job's command and log its output, exit code, and execution time.
    """
    start_time = datetime.now()

    # Load environment variables from env_file
    env = os.environ.copy()
    if env_file and os.path.exists(env_file):
        with open(env_file) as f:
            env.update(
                dict(line.strip().split("=", 1) for line in f if line.strip() and not line.startswith("#"))
            )

    # Execute the command
    process = Popen([interpreter, "-c", command], stdout=PIPE, stderr=PIPE, env=env)
    stdout, stderr = process.communicate()
    exit_code = process.returncode

    # Log execution details
    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()
    log_to_db(job_id, exit_code, execution_time)
    log_to_file(job_id, exit_code, execution_time, stdout, stderr)

def log_to_db(job_id, exit_code, execution_time):
    """
    Log job execution details to SQLite database.
    """
    conn = sqlite3.connect(CONFIG["settings"]["db_path"])
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO job_execution_logs (job_id, exit_code, execution_time, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (job_id, exit_code, execution_time, datetime.now()),
    )
    conn.commit()
    conn.close()

def log_to_file(job_id, exit_code, execution_time, stdout, stderr):
    """
    Log job execution details to a log file.
    """
    with open(LOG_FILE, "a") as log:
        log.write(f"[{datetime.now()}] Job {job_id}: Exit Code={exit_code}, Execution Time={execution_time}s\n")
        if stdout:
            log.write(f"STDOUT:\n{stdout.decode()}\n")
        if stderr:
            log.write(f"STDERR:\n{stderr.decode()}\n")

# Schedule Jobs
def schedule_jobs(jobs):
    """
    Add jobs to the APScheduler based on their configuration.
    """
    for job_id, job in jobs.items():
        interpreter = CONFIG["interpreters"].get(job["type"], "")
        if not interpreter:
            logging.warning(f"Interpreter for job {job_id} not found.")
            continue

        # Check for conditions
        condition = job.get("condition")
        if condition:
            condition_met = evaluate_condition(
                condition, CONFIG["settings"]["db_path"], job_id
            )
            if not condition_met:
                logging.info(f"Skipping job {job_id} because its condition is not met.")
                continue

        # Determine schedule
        schedule_type = job.get("schedule_type", "cron")
        if schedule_type == "cron":
            trigger = CronTrigger.from_crontab(job["schedule"])
        else:
            trigger = IntervalTrigger(seconds=job["interval_seconds"])

        scheduler.add_job(
            func=run_job,
            args=[job_id, interpreter, job["command"], job.get("env_file")],
            trigger=trigger,
            id=job_id,
            name=job.get("name", f"Job {job_id}"),
            replace_existing=True,
        )

def start_daemon(daemonize=False):
    """
    Start the job scheduler daemon.
    """
    global CONFIG

    init_db(CONFIG["settings"]["db_path"])
    schedule_jobs(CONFIG["jobs"])

    # Get the PID file path from config
    pid_file = CONFIG["settings"].get("pid_file", "/tmp/avscheduler.pid")

    # Start the Flask web interface
    web_host = CONFIG["web_server"].get("host", "127.0.0.1")
    web_port = CONFIG["web_server"].get("port", 5000)

    def start_flask():
        web_ui.app.run(host=web_host, port=web_port, debug=False)

    if daemonize:
        # Daemonize using python-daemon or custom method
        with DaemonContext():
            write_pid(pid_file)
            flask_thread = start_flask_in_thread()
            try:
                scheduler.start()
                flask_thread.join()
            finally:
                remove_pid(pid_file)
    else:
        write_pid(pid_file)
        flask_thread = start_flask_in_thread()
        try:
            scheduler.start()
            flask_thread.join()
        finally:
            remove_pid(pid_file)

def start_flask_in_thread():
    """
    Start the Flask app in a separate thread.
    """
    from threading import Thread
    flask_thread = Thread(target=lambda: web_ui.app.run(debug=False))
    flask_thread.daemon = True
    flask_thread.start()
    return flask_thread


if __name__ == "__main__":
    start_daemon(daemonize=True)
