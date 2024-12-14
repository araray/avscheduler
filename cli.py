import click
import os
import toml
import sqlite3
from tabulate import tabulate
from scheduler import start_daemon, CONFIG, load_config, scheduler
from models import init_db

CONFIG_FILE = "config.toml"


@click.group()
def cli():
    """
    Job Scheduler CLI: Manage jobs, daemon, and configuration.
    """
    global CONFIG
    CONFIG = load_config(CONFIG_FILE)


@click.command()
@click.option("--daemonize", is_flag=True, help="Run the scheduler as a daemon.")
def start(daemonize):
    """
    Start the daemon.
    """
    click.echo("Starting the scheduler daemon...")
    from scheduler import start_daemon
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
    click.echo("Stopping the scheduler daemon...")
    scheduler.shutdown(wait=False)
    click.echo("Scheduler daemon stopped.")


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
    List all configured jobs from the configuration file.
    """
    config = load_config(CONFIG_FILE)
    jobs = config.get("jobs", {})
    if not jobs:
        click.echo("No jobs found in the configuration.")
        return

    table = [
        [job_id, job.get("type"), job.get("schedule"), job.get("command"), job.get("condition", "N/A")]
        for job_id, job in jobs.items()
    ]
    headers = ["Job ID", "Type", "Schedule", "Command", "Condition"]
    click.echo(tabulate(table, headers=headers, tablefmt="grid"))


@click.command()
@click.argument("job_id")
def run_job(job_id):
    """
    Manually run a specific job by its ID.
    """
    config = load_config(CONFIG_FILE)
    job = config.get("jobs", {}).get(job_id)

    if not job:
        click.echo(f"Job '{job_id}' not found.")
        return

    from scheduler import run_job
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
cli.add_command(list_jobs)
cli.add_command(run_job)
cli.add_command(add_job)
cli.add_command(edit_job)
cli.add_command(delete_job)
cli.add_command(view_logs)
cli.add_command(reload_config)

if __name__ == "__main__":
    cli()
