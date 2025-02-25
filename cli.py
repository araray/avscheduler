"""
    Job Scheduler CLI: Manage jobs, daemon, and configuration.
"""

import os
import signal
import sqlite3
import toml

import click

from tabulate import tabulate

from scheduler import start_daemon, CONFIG, load_config, scheduler, run_job
from utils import get_valid_directory


config_path = get_valid_directory()
CONFIG_FILE = os.path.join(str(config_path), "config.toml")


@click.group()
@click.option("--config", "-c", default=CONFIG_FILE, help="Path to a configuration file")
def cli(config):
    """
    Job Scheduler CLI: Manage jobs, daemon, and configuration.
    """
    global CONFIG
    CONFIG = load_config(config)


@click.command()
@click.option("--daemonize", is_flag=True, help="Run the scheduler as a daemon.")
def start(daemonize):
    """
    Start the daemon.
    """
    config = load_config(CONFIG_FILE)
    CONFIG = config
    pid_file = config["settings"].get("pid_file", "/tmp/avscheduler.pid")

    # Check if the daemon is already running
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        if os.path.exists(f"/proc/{pid}"):
            click.echo(f"Daemon is already running with PID {pid}.")
            return

    click.echo("Starting the scheduler daemon...")
    start_daemon(daemonize=daemonize)
    if daemonize:
        click.echo("Scheduler daemon started in background.")
    else:
        click.echo("Scheduler running in the foreground...")



@click.command()
def stop():
    """
    Stop the scheduler daemon.
    """
    config = load_config(CONFIG_FILE)
    pid_file = config["settings"].get("pid_file", "/tmp/avscheduler.pid")

    if not os.path.exists(pid_file):
        click.echo(f"Error: PID file {pid_file} not found. Is the daemon running?")
        return

    # Read the PID from the file
    with open(pid_file, "r") as f:
        pid = int(f.read().strip())

    try:
        # Send SIGTERM to the daemon
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Daemon with PID {pid} stopped.")
    except ProcessLookupError:
        click.echo(f"Error: No process found with PID {pid}. Removing stale PID file.")
        os.remove(pid_file)
    except PermissionError:
        click.echo(f"Error: Permission denied to stop the process with PID {pid}.")


@click.command()
def status():
    """
    Check the status of the scheduler daemon.
    """
    config = load_config(CONFIG_FILE)
    pid_file = config["settings"].get("pid_file", "/tmp/avscheduler.pid")

    if not os.path.exists(pid_file):
        click.echo("Scheduler daemon is not running (no PID file found).")
        return

    # Read the PID and check if the process is alive
    with open(pid_file, "r") as f:
        pid = int(f.read().strip())

    if os.path.exists(f"/proc/{pid}"):
        click.echo(f"Scheduler daemon is running with PID {pid}.")
    else:
        click.echo("Scheduler daemon is not running (stale PID file found).")
        os.remove(pid_file)


@click.command()
def restart():
    """
    Restart the scheduler daemon.
    """
    click.echo("Restarting the scheduler daemon...")
    scheduler.shutdown(wait=False)
    start_daemon()
    click.echo("Scheduler daemon restarted.")


@click.command()
def list_jobs():
    """
    List all configured jobs along with their execution status and schedule.
    """
    config = load_config(CONFIG_FILE)
    jobs = config.get("jobs", {})
    if not jobs:
        click.echo("No jobs found in the configuration.")
        return

    # Connect to the database to fetch job logs
    conn = sqlite3.connect(config["settings"]["db_path"])
    cursor = conn.cursor()

    # Fetch job execution history for each job
    results = {}
    for job_id in jobs.keys():
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
        row = cursor.fetchone()
        if row:
            last_execution, last_exit_code, last_execution_time = row
        else:
            last_execution, last_exit_code, last_execution_time = "N/A", "N/A", "N/A"

        # Get the next scheduled run from APScheduler
        apscheduler_job = scheduler.get_job(job_id)
        next_run_time = apscheduler_job.next_run_time if apscheduler_job else "N/A"

        results[job_id] = {
            "last_execution": last_execution,
            "last_exit_code": last_exit_code,
            "last_execution_time": last_execution_time,
            "next_run_time": next_run_time,
            "condition": jobs[job_id].get("condition", "N/A"),
        }

    conn.close()

    # Display results in a table
    table = [
        [
            job_id,
            data["last_execution"],
            data["last_exit_code"],
            data["last_execution_time"],
            data["next_run_time"],
            data["condition"],
        ]
        for job_id, data in results.items()
    ]
    headers = [
        "Job ID",
        "Last Execution",
        "Last Exit Code",
        "Last Execution Time (s)",
        "Next Run Time",
        "Condition",
    ]
    click.echo(tabulate(table, headers=headers, tablefmt="grid"))


@click.command()
@click.argument("job_id")
def run_single_job(job_id):
    """
    Manually run a specific job by its ID.
    """
    config = load_config(CONFIG_FILE)
    job = config.get("jobs", {}).get(job_id)

    if not job:
        click.echo(f"Job '{job_id}' not found.")
        return

    interpreter = CONFIG["interpreters"].get(job["type"])
    if not interpreter:
        click.echo(f"Interpreter for job '{job_id}' not configured.")
        return

    click.echo(f"Running job '{job_id}'...")
    run_job(job_id, interpreter, job["command"], job.get("env_file"))
    click.echo(f"Job '{job_id}' executed.")


@click.command()
@click.argument("job_id")
@click.option("--type", prompt="Job Type (PYTHON, BASH, etc.)", help="Interpreter type")
@click.option("--schedule", prompt="Job Schedule (Cron format)", help="Job schedule in cron format")
@click.option("--command", prompt="Job Command", help="Command to execute")
@click.option("--condition", default=None, help="Optional job condition")
@click.option("--env-file", default=None, help="Path to an environment file")
def add_job(job_id, type, schedule, command, condition, env_file):
    """
    Add a new job to the configuration.
    """
    config = load_config(CONFIG_FILE)
    jobs = config.setdefault("jobs", {})

    if job_id in jobs:
        click.echo(f"Job '{job_id}' already exists.")
        return

    jobs[job_id] = {
        "type": type,
        "schedule": schedule,
        "command": command,
        "condition": condition,
        "env_file": env_file,
    }

    with open(CONFIG_FILE, "w") as f:
        toml.dump(config, f)

    click.echo(f"Job '{job_id}' added successfully.")


@click.command()
@click.argument("job_id")
@click.option("--type", help="Interpreter type (PYTHON, BASH, etc.)")
@click.option("--schedule", help="Job schedule in cron format")
@click.option("--command", help="Command to execute")
@click.option("--condition", help="Optional job condition")
@click.option("--env-file", help="Path to an environment file")
def edit_job(job_id, type, schedule, command, condition, env_file):
    """
    Edit an existing job in the configuration.
    """
    config = load_config(CONFIG_FILE)
    jobs = config.get("jobs", {})

    if job_id not in jobs:
        click.echo(f"Job '{job_id}' not found.")
        return

    job = jobs[job_id]

    if type:
        job["type"] = type
    if schedule:
        job["schedule"] = schedule
    if command:
        job["command"] = command
    if condition:
        job["condition"] = condition
    if env_file:
        job["env_file"] = env_file

    with open(CONFIG_FILE, "w") as f:
        toml.dump(config, f)

    click.echo(f"Job '{job_id}' updated successfully.")


@click.command()
@click.argument("job_id")
def delete_job(job_id):
    """
    Delete a job from the configuration.
    """
    config = load_config(CONFIG_FILE)
    jobs = config.get("jobs", {})

    if job_id not in jobs:
        click.echo(f"Job '{job_id}' not found.")
        return

    del jobs[job_id]

    with open(CONFIG_FILE, "w") as f:
        toml.dump(config, f)

    click.echo(f"Job '{job_id}' deleted successfully.")


@click.command()
@click.option("--job-id", help="Job ID to filter logs", default=None)
def view_logs(job_id):
    """
    View execution logs for all jobs or a specific job.
    """
    # Ensure configuration is loaded
    config = load_config(CONFIG_FILE)

    # Validate that "settings" exists in the configuration
    if "settings" not in config or "db_path" not in config["settings"]:
        click.echo("Error: Missing 'settings' or 'db_path' in the configuration file.")
        return

    # Connect to the database
    conn = sqlite3.connect(config["settings"]["db_path"])
    cursor = conn.cursor()

    # Fetch logs
    if job_id:
        cursor.execute(
            """
            SELECT * FROM job_execution_logs WHERE job_id = ? ORDER BY timestamp DESC
            """,
            (job_id,),
        )
    else:
        cursor.execute("SELECT * FROM job_execution_logs ORDER BY timestamp DESC")

    logs = cursor.fetchall()
    conn.close()

    if not logs:
        click.echo("No logs found.")
        return

    headers = ["ID", "Job ID", "Exit Code", "Execution Time (s)", "Timestamp"]
    click.echo(tabulate(logs, headers=headers, tablefmt="grid"))

@click.command()
@click.argument("job_id")
@click.option("--before", help="Delete logs before a specific timestamp (format: YYYY-MM-DD HH:MM:SS).")
@click.option("--all", is_flag=True, help="Delete all logs for the specified job.")
def cleanup_logs(job_id, before, all):
    """
    Clean up execution logs for a specific job.
    """
    config = load_config(CONFIG_FILE)
    db_path = config["settings"]["db_path"]

    if not all and not before:
        click.echo("You must specify either --before or --all.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        if all:
            cursor.execute("DELETE FROM job_execution_logs WHERE job_id = ?", (job_id,))
            click.echo(f"Deleted all logs for job '{job_id}'.")
        elif before:
            cursor.execute(
                "DELETE FROM job_execution_logs WHERE job_id = ? AND timestamp < ?",
                (job_id, before),
            )
            click.echo(f"Deleted logs for job '{job_id}' before {before}.")
        conn.commit()
    except Exception as e:
        click.echo(f"Error cleaning logs: {e}")
    finally:
        conn.close()


@click.command()
def reload_config():
    """
    Reload the configuration file without restarting the daemon.
    """
    global CONFIG
    CONFIG = load_config(CONFIG_FILE)
    click.echo("Configuration reloaded successfully.")


# Add commands to CLI group
cli.add_command(start)
cli.add_command(stop)
cli.add_command(restart)
cli.add_command(status)
cli.add_command(list_jobs)
cli.add_command(cleanup_logs)
cli.add_command(run_single_job)
cli.add_command(add_job)
cli.add_command(edit_job)
cli.add_command(delete_job)
cli.add_command(view_logs)
cli.add_command(reload_config)


if __name__ == "__main__":
    cli()
