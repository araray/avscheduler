# cli.py

"""
Command Line Interface for managing the AVScheduler daemon, jobs, and logs.
Uses the refactored core logic.
"""

import os
import sys
import signal
import toml
import click
import logging
from datetime import datetime
from tabulate import tabulate

# Adjust path to import from core and utils if necessary
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    # Core components
    from core.scheduler_logic import (
        load_config,
        write_pid, remove_pid, read_pid, is_process_running,
        add_or_update_job_in_scheduler, remove_job_from_scheduler,
        execute_job_command, # For run-job command
        scheduler as global_scheduler # Access the scheduler instance if needed (e.g., for reload)
    )
    from core.database import (
        init_db as core_init_db,
        get_latest_job_log, get_job_logs, delete_job_logs,
        JobExecutionLog # Import model for type hinting if needed
    )
    # Utils
    from utils import get_valid_directory
except ImportError as e:
    print(f"Error importing core modules in cli.py: {e}", file=sys.stderr)
    print("Ensure the project structure is correct and PYTHONPATH is set if needed.", file=sys.stderr)
    sys.exit(1)

# Configure basic logging for CLI operations
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [CLI] %(message)s')
logger = logging.getLogger(__name__)

# --- Global Config Variable (Loaded per command) ---
# This approach reloads config for each command, ensuring freshness but potentially less efficient.
# Alternatively, load once in the group context if commands don't modify it frequently.
# CONFIG = {} # Removed global CONFIG, load per command

# --- Helper to get config path ---
def resolve_config_path(ctx, param, value):
    """Resolves the config path, using default if necessary."""
    if value:
        return value
    # Default path resolution logic (similar to scheduler.py)
    try:
        base_dir = get_valid_directory()
        if base_dir:
            default_path = os.path.join(base_dir, "config.toml")
        else:
            default_path = os.path.join(project_root, "config.toml")
        logger.debug(f"Using default config path: {default_path}")
        return default_path
    except Exception as e:
        logger.error(f"Error determining default config path: {e}")
        # Fallback if utils fail
        return os.path.join(project_root, "config.toml")


# --- CLI Group ---
@click.group()
@click.option(
    "--config", "-c",
    type=click.Path(dir_okay=False),
    callback=resolve_config_path, # Use callback to resolve default path
    help="Path to the configuration file."
)
@click.pass_context # Pass context to access config path in commands
def cli(ctx, config):
    """
    AVScheduler CLI: Manage the scheduler daemon, jobs, and logs.
    """
    # Store the resolved config path in the context object
    ctx.ensure_object(dict)
    ctx.obj['CONFIG_PATH'] = config
    logger.debug(f"CLI using configuration file: {config}")


# --- Daemon Commands ---

@cli.command()
@click.option("--foreground", is_flag=True, help="Run the scheduler in the foreground (debugging).")
@click.pass_context
def start(ctx, foreground):
    """
    Start the scheduler daemon process.
    Note: Daemonization should ideally be handled by a process manager (systemd, supervisor).
          This command starts the scheduler logic directly.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    pid_file = config.get("settings", {}).get("pid_file")
    if not pid_file:
        click.echo("Error: 'pid_file' not defined in configuration [settings].", err=True)
        sys.exit(1)

    # Check if already running
    pid = read_pid(pid_file)
    if pid and is_process_running(pid):
        click.echo(f"Scheduler appears to be already running with PID {pid} (PID file: {pid_file}).")
        return
    elif pid:
        click.echo(f"Warning: Found stale PID file '{pid_file}' for PID {pid}. Removing it.")
        remove_pid(pid_file) # Remove stale PID file

    click.echo("Starting the scheduler...")

    if foreground:
        click.echo("Running in foreground. Press Ctrl+C to stop.")
        # Directly call the core start function (which blocks)
        try:
             # Import here to avoid loading scheduler logic unless starting
             from core.scheduler_logic import start_scheduler_process
             start_scheduler_process(config)
        except Exception as e:
             click.echo(f"Scheduler failed to start or exited unexpectedly: {e}", err=True)
             # Ensure PID is cleaned up if start_scheduler_process failed early
             if read_pid(pid_file) == os.getpid():
                 remove_pid(pid_file)
             sys.exit(1)
    else:
        click.echo("Starting in background (simulated - use systemd or similar for true daemonization).")
        # In a real scenario, you'd use python-daemon or fork here.
        # For simplicity, we'll just launch scheduler.py as a detached process.
        # This is NOT robust daemonization.
        try:
            # Use sys.executable to ensure the same Python interpreter is used
            cmd = [sys.executable, os.path.join(project_root, 'scheduler.py'), '--config', config_path]
            # Use Popen to detach
            p = Popen(cmd, stdout=open(os.devnull, 'w'), stderr=open(os.devnull, 'w'), start_new_session=True)
            click.echo(f"Scheduler process launched in background (PID: {p.pid}). Monitor logs for status.")
            # We don't have the actual daemon PID here easily without more complex IPC.
            # The PID file will be written by the scheduler.py process itself.
            click.echo("Check PID file and logs for confirmation.")
        except Exception as e:
            click.echo(f"Failed to launch background process: {e}", err=True)
            sys.exit(1)


@cli.command()
@click.pass_context
def stop(ctx):
    """
    Stop the running scheduler daemon process via its PID file.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        # Load config just to get the pid_file path
        config = load_config(config_path)
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file:
             click.echo("Error: 'pid_file' not defined in [settings]. Cannot determine process PID.", err=True)
             sys.exit(1)
    except FileNotFoundError:
        # If config is gone, maybe PID file still exists? Try default path.
        click.echo(f"Warning: Config file '{config_path}' not found. Trying default PID path logic.", err=True)
        try:
            base_dir = get_valid_directory()
            pid_file = os.path.join(base_dir or project_root, "logs", "avscheduler.pid")
            click.echo(f"Attempting PID file: {pid_file}")
        except Exception:
             click.echo("Error: Cannot determine PID file path without configuration.", err=True)
             sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)


    pid = read_pid(pid_file)
    if not pid:
        click.echo(f"Scheduler not running (PID file '{pid_file}' not found or empty).")
        return

    if not is_process_running(pid):
        click.echo(f"Scheduler not running (process PID {pid} not found). Removing stale PID file '{pid_file}'.")
        remove_pid(pid_file)
        return

    click.echo(f"Stopping scheduler process with PID {pid}...")
    try:
        # Send SIGTERM for graceful shutdown
        os.kill(pid, signal.SIGTERM)
        # Wait briefly to see if it exits (optional)
        import time
        for _ in range(5): # Wait up to 5 seconds
             if not is_process_running(pid):
                 click.echo(f"Scheduler process {pid} stopped gracefully.")
                 remove_pid(pid_file) # Clean up PID file
                 return
             time.sleep(1)

        # If still running, maybe force kill (use with caution)
        click.echo(f"Scheduler process {pid} did not stop gracefully after 5s. Consider manual check or kill -9 {pid}.", err=True)
        # os.kill(pid, signal.SIGKILL) # Uncomment if force kill is desired

    except ProcessLookupError:
        click.echo(f"Error: Process with PID {pid} not found (already stopped?). Removing stale PID file.")
        remove_pid(pid_file)
    except PermissionError:
        click.echo(f"Error: Permission denied to stop process PID {pid}. Try with sudo?", err=True)
    except Exception as e:
        click.echo(f"An error occurred while stopping the process: {e}", err=True)


@cli.command()
@click.pass_context
def status(ctx):
    """
    Check the status of the scheduler daemon via its PID file.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file:
             click.echo("Error: 'pid_file' not defined in [settings]. Cannot determine status.", err=True)
             sys.exit(1)
    except FileNotFoundError:
        click.echo(f"Warning: Config file '{config_path}' not found. Status check might be inaccurate.", err=True)
        try: # Try default pid path
            base_dir = get_valid_directory()
            pid_file = os.path.join(base_dir or project_root, "logs", "avscheduler.pid")
        except Exception:
            click.echo("Error: Cannot determine PID file path without configuration.", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    pid = read_pid(pid_file)
    if not pid:
        click.echo(f"Scheduler is stopped (PID file '{pid_file}' not found or empty).")
        return

    if is_process_running(pid):
        click.echo(f"Scheduler is running with PID {pid} (PID file: {pid_file}).")
    else:
        click.echo(f"Scheduler is stopped (PID file '{pid_file}' found for PID {pid}, but process is not running - stale PID file).")
        # Optionally offer to remove stale PID file here


@cli.command()
@click.pass_context
def restart(ctx):
    """
    Stop and then start the scheduler daemon.
    """
    click.echo("Attempting to restart the scheduler...")
    # Call stop command logic
    ctx.invoke(stop)
    # Add a small delay before starting again
    import time
    time.sleep(2)
    # Call start command logic
    ctx.invoke(start)
    click.echo("Restart sequence initiated. Check status and logs.")


# --- Job Management Commands ---

@cli.command("list-jobs")
@click.pass_context
def list_jobs(ctx):
    """
    List all configured jobs and their last known status.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        db_path = config.get("settings", {}).get("db_path")
        if not db_path:
            click.echo("Error: 'db_path' not defined in [settings]. Cannot fetch job status.", err=True)
            sys.exit(1)
        # Initialize DB for reading logs
        core_init_db(db_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True)
        sys.exit(1)

    jobs = config.get("jobs", {})
    if not jobs:
        click.echo("No jobs found in the configuration.")
        return

    results_table = []
    headers = [
        "Job ID", "Type", "Schedule", "Condition",
        "Last Run", "Last Exit", "Last Duration (s)", "Next Run (Live*)"
    ]

    # Try to get live scheduler info if daemon is running
    pid_file = config.get("settings", {}).get("pid_file")
    pid = read_pid(pid_file) if pid_file else None
    is_running = pid and is_process_running(pid)
    scheduler_instance = None
    if is_running:
        # This is tricky. The CLI doesn't have direct access to the running
        # scheduler instance's memory. We *cannot* reliably get the live
        # next_run_time here without IPC or accessing a shared state
        # that the daemon updates (e.g., status file, DB table).
        # For now, we'll indicate it's live but won't fetch it.
        # Option: Could try importing global_scheduler, but it won't reflect the daemon's state.
        pass # Cannot get live state easily

    click.echo("Fetching job status from configuration and logs...")
    click.echo("(*) Next Run Time requires the scheduler daemon to be running and accessible (currently not implemented in CLI).")


    for job_id, job_config in jobs.items():
        latest_log = get_latest_job_log(job_id) # Fetches from DB

        # Get schedule info from config
        schedule_type = job_config.get("schedule_type", "N/A")
        if schedule_type == "cron":
            schedule_info = f"Cron: {job_config.get('schedule', 'Not Set')}"
        elif schedule_type == "interval":
            secs = job_config.get('interval_seconds', 'N/A')
            schedule_info = f"Interval: {secs}s"
        elif schedule_type == "date":
            schedule_info = f"Date: {job_config.get('run_date', 'Not Set')}"
        else:
            schedule_info = "N/A"

        # Get next run time (placeholder)
        next_run_time_str = "N/A"
        # if scheduler_instance: # If we could access the live instance
        #     aps_job = scheduler_instance.get_job(job_id)
        #     next_run_time_str = aps_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z') if aps_job and aps_job.next_run_time else "N/A"


        results_table.append([
            job_id,
            job_config.get("type", "N/A"),
            schedule_info,
            job_config.get("condition", "N/A"),
            latest_log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_log else "N/A",
            latest_log.exit_code if latest_log else "N/A",
            f"{latest_log.execution_time:.3f}" if latest_log else "N/A",
            next_run_time_str # Placeholder
        ])

    # Sort by Job ID
    results_table.sort(key=lambda row: row[0])

    click.echo(tabulate(results_table, headers=headers, tablefmt="grid"))


@cli.command("run-job")
@click.argument("job_id")
@click.option("--timeout", type=int, help="Optional execution timeout in seconds.")
@click.pass_context
def run_single_job(ctx, job_id, timeout):
    """
    Manually run a specific job by its ID, bypassing schedule and conditions.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        db_path = config.get("settings", {}).get("db_path")
        if not db_path:
            click.echo("Error: 'db_path' not defined in [settings]. Cannot log job execution.", err=True)
            sys.exit(1)
        # Initialize DB for logging
        core_init_db(db_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True)
        sys.exit(1)

    job_config = config.get("jobs", {}).get(job_id)
    if not job_config:
        click.echo(f"Error: Job '{job_id}' not found in configuration.", err=True)
        return

    interpreter_type = job_config.get("type")
    interpreter_path = config.get("interpreters", {}).get(interpreter_type)
    command = job_config.get("command")
    env_file = job_config.get("env_file")

    if not interpreter_path:
        click.echo(f"Error: Interpreter type '{interpreter_type}' for job '{job_id}' not defined in [interpreters].", err=True)
        return
    if not command:
        click.echo(f"Error: Job '{job_id}' has no command defined.", err=True)
        return

    click.echo(f"Manually running job '{job_id}'...")
    click.echo(f"Interpreter: {interpreter_path}")
    click.echo(f"Command: {command}")
    if env_file:
        click.echo(f"Env File: {env_file}")
    if timeout:
        click.echo(f"Timeout: {timeout}s")

    # Execute directly using the core function
    exit_code, exec_time, stdout, stderr = execute_job_command(
        job_id, interpreter_path, command, env_file, timeout
    )

    click.echo(f"\n--- Job '{job_id}' Execution Finished ---")
    click.echo(f"Exit Code: {exit_code}")
    click.echo(f"Duration: {exec_time:.3f}s")
    if stdout:
        click.echo(f"--- STDOUT ---\n{stdout.strip()}")
    if stderr:
        click.echo(f"--- STDERR ---\n{stderr.strip()}")

    # Log to database
    from core.database import log_job_execution
    log_job_execution(job_id, exit_code, exec_time, stdout, stderr)
    click.echo("Execution result logged to database.")


@cli.command("add-job")
@click.argument("job_id")
@click.option("--type", required=True, prompt="Job Type (e.g., PYTHON, BASH)", help="Interpreter type (must exist in [interpreters])")
@click.option("--schedule-type", required=True, type=click.Choice(['cron', 'interval', 'date']), prompt=True)
# Conditional prompts/options based on schedule_type
@click.option("--schedule", help="Cron schedule string (e.g., '0 * * * *'). Required if schedule-type=cron.")
@click.option("--interval-seconds", type=int, help="Interval in seconds. Required if schedule-type=interval.")
@click.option("--run-date", help="Specific run date/time (ISO format: YYYY-MM-DD HH:MM:SS). Required if schedule-type=date.")
@click.option("--command", required=True, prompt=True, help="Command string to execute.")
@click.option("--condition", help="Optional execution condition string.")
@click.option("--env-file", type=click.Path(exists=True, dir_okay=False), help="Optional path to an environment file.")
@click.option("--timeout", type=int, help="Optional execution timeout in seconds for this job.")
@click.pass_context
def add_job(ctx, job_id, type, schedule_type, schedule, interval_seconds, run_date, command, condition, env_file, timeout):
    """
    Add a new job definition to the configuration file.
    Requires manual 'reload-config' or daemon restart to take effect.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        # If config doesn't exist, start with an empty structure
        click.echo(f"Info: Configuration file '{config_path}' not found. Creating a new one.")
        config = {"settings": {}, "interpreters": {}, "jobs": {}, "web_server": {}}
        # Try to populate default settings if possible
        try:
            base_dir = get_valid_directory()
            config['settings']['db_path'] = os.path.join(base_dir or project_root, "jobs.db")
            config['settings']['pid_file'] = os.path.join(base_dir or project_root, "logs", "avscheduler.pid")
            config['web_server']['host'] = "127.0.0.1"
            config['web_server']['port'] = 5000
        except Exception:
            click.echo("Warning: Could not determine default paths for new config.", err=True)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    # Validate interpreter type
    if type not in config.get("interpreters", {}):
        click.echo(f"Error: Interpreter type '{type}' is not defined in the [interpreters] section of '{config_path}'. Add it first.", err=True)
        return

    jobs = config.setdefault("jobs", {})
    if job_id in jobs:
        click.echo(f"Error: Job '{job_id}' already exists in the configuration.", err=True)
        return

    # Validate schedule options based on type
    new_job = {"type": type, "schedule_type": schedule_type, "command": command}
    if schedule_type == "cron":
        if not schedule:
            click.echo("Error: --schedule is required for schedule-type 'cron'.", err=True)
            return
        new_job["schedule"] = schedule
    elif schedule_type == "interval":
        if interval_seconds is None:
            click.echo("Error: --interval-seconds is required for schedule-type 'interval'.", err=True)
            return
        new_job["interval_seconds"] = interval_seconds
    elif schedule_type == "date":
        if not run_date:
            click.echo("Error: --run-date is required for schedule-type 'date'.", err=True)
            return
        # Basic validation for date format (can be improved)
        try:
            datetime.fromisoformat(run_date)
        except ValueError:
            click.echo("Error: Invalid format for --run-date. Use ISO format (YYYY-MM-DD HH:MM:SS).", err=True)
            return
        new_job["run_date"] = run_date

    # Add optional fields
    if condition:
        new_job["condition"] = condition
    if env_file:
        new_job["env_file"] = env_file # Already validated path existence by click
    if timeout is not None:
        new_job["timeout_seconds"] = timeout

    # Add to config structure
    jobs[job_id] = new_job

    # Write updated config back to file
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' added to configuration file '{config_path}'.")
        click.echo("Run 'reload-config' or restart the daemon for changes to take effect.")
    except IOError as e:
        click.echo(f"Error writing configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


@cli.command("edit-job")
@click.argument("job_id")
# Allow editing specific fields
@click.option("--type", help="New interpreter type.")
@click.option("--schedule-type", type=click.Choice(['cron', 'interval', 'date']), help="New schedule type.")
@click.option("--schedule", help="New cron schedule string.")
@click.option("--interval-seconds", type=int, help="New interval in seconds.")
@click.option("--run-date", help="New specific run date/time (ISO format).")
@click.option("--command", help="New command string.")
@click.option("--condition", help="New execution condition string (use '' to remove).")
@click.option("--env-file", help="New path to an environment file (use '' to remove).")
@click.option("--timeout", type=int, help="New execution timeout in seconds (use -1 to remove).")
@click.pass_context
def edit_job(ctx, job_id, **kwargs):
    """
    Edit properties of an existing job in the configuration file.
    Requires manual 'reload-config' or daemon restart to take effect.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    jobs = config.get("jobs", {})
    if job_id not in jobs:
        click.echo(f"Error: Job '{job_id}' not found in the configuration.", err=True)
        return

    job_data = jobs[job_id]
    updated_fields = 0

    # Iterate through provided options and update job_data
    for key, value in kwargs.items():
        if value is not None: # Only update if option was provided
            # Handle special cases for removal
            if key in ["condition", "env_file"] and value == '':
                 if key in job_data:
                     del job_data[key]
                     click.echo(f"Removing {key} for job '{job_id}'.")
                     updated_fields += 1
                 else:
                      click.echo(f"Field {key} not present for job '{job_id}', cannot remove.")
            elif key == "timeout" and value == -1:
                 if "timeout_seconds" in job_data:
                     del job_data["timeout_seconds"]
                     click.echo(f"Removing timeout for job '{job_id}'.")
                     updated_fields += 1
                 else:
                     click.echo(f"Timeout not set for job '{job_id}', cannot remove.")
            else:
                # Normal update
                field_name = key if key != "timeout" else "timeout_seconds"

                # Validate type if necessary (e.g., interpreter)
                if field_name == "type" and value not in config.get("interpreters", {}):
                     click.echo(f"Error: Interpreter type '{value}' is not defined in [interpreters].", err=True)
                     continue # Skip this update

                # Validate schedule consistency
                if field_name == "schedule_type":
                     # Clear out old schedule fields when type changes
                     job_data.pop("schedule", None)
                     job_data.pop("interval_seconds", None)
                     job_data.pop("run_date", None)
                # TODO: Add validation that required fields for the *new* type are provided later

                # Validate date format
                if field_name == "run_date":
                     try:
                         datetime.fromisoformat(value)
                     except (ValueError, TypeError):
                         click.echo(f"Error: Invalid format for --run-date '{value}'. Use ISO format.", err=True)
                         continue # Skip this update

                # Update the value
                job_data[field_name] = value
                click.echo(f"Updating {field_name} for job '{job_id}'.")
                updated_fields += 1

    # TODO: Add validation after all updates to ensure schedule consistency
    # (e.g., if schedule_type is 'cron', 'schedule' must exist)

    if updated_fields == 0:
        click.echo("No changes provided to update.")
        return

    # Write updated config back to file
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' updated in configuration file '{config_path}'.")
        click.echo("Run 'reload-config' or restart the daemon for changes to take effect.")
    except IOError as e:
        click.echo(f"Error writing configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


@cli.command("delete-job")
@click.argument("job_id")
@click.confirmation_option(prompt='Are you sure you want to delete this job from the configuration?')
@click.pass_context
def delete_job(ctx, job_id):
    """
    Delete a job definition from the configuration file.
    Requires manual 'reload-config' or daemon restart to take effect.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    jobs = config.get("jobs", {})
    if job_id not in jobs:
        click.echo(f"Error: Job '{job_id}' not found in the configuration.", err=True)
        return

    # Delete the job
    del jobs[job_id]

    # Write updated config back to file
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' deleted from configuration file '{config_path}'.")
        click.echo("Run 'reload-config' or restart the daemon for changes to take effect.")
    except IOError as e:
        click.echo(f"Error writing configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


# --- Log Management Commands ---

@cli.command("view-logs")
@click.option("--job-id", default=None, help="Filter logs for a specific Job ID.")
@click.option("--limit", type=int, default=50, help="Maximum number of log entries to display.")
@click.pass_context
def view_logs(ctx, job_id, limit):
    """
    View job execution logs from the database.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        db_path = config.get("settings", {}).get("db_path")
        if not db_path:
            click.echo("Error: 'db_path' not defined in [settings]. Cannot view logs.", err=True)
            sys.exit(1)
        # Initialize DB for reading logs
        core_init_db(db_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True)
        sys.exit(1)

    click.echo(f"Fetching logs{' for job ' + job_id if job_id else ''} (limit {limit})...")

    try:
        # Use the core database function to get logs
        if job_id:
            logs = get_job_logs(job_id, limit=limit)
        else:
            # Need a function to get all logs (potentially slow)
            # Let's add a get_all_logs function to core.database
            # For now, simulate by querying directly (less ideal)
            session = core_get_session()
            logs = session.query(JobExecutionLog)\
                          .order_by(JobExecutionLog.timestamp.desc())\
                          .limit(limit)\
                          .all()
            session.close()


        if not logs:
            click.echo("No logs found matching the criteria.")
            return

        # Prepare data for tabulation
        headers = ["Log ID", "Job ID", "Timestamp", "Exit Code", "Duration (s)", "Output Snippet"]
        table_data = []
        for log in logs:
            # Create a snippet of stdout/stderr
            output_snippet = ""
            if log.stderr:
                output_snippet = f"STDERR: {log.stderr[:50]}{'...' if len(log.stderr) > 50 else ''}"
            elif log.stdout:
                 output_snippet = f"STDOUT: {log.stdout[:50]}{'...' if len(log.stdout) > 50 else ''}"

            table_data.append([
                log.id,
                log.job_id,
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.exit_code,
                f"{log.execution_time:.3f}",
                output_snippet
            ])

        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))

    except Exception as e:
        click.echo(f"Error retrieving logs from database: {e}", err=True)


@cli.command("cleanup-logs")
@click.argument("job_id")
@click.option("--before", help="Delete logs before this timestamp (ISO format: YYYY-MM-DD HH:MM:SS).")
@click.option("--all", is_flag=True, help="Delete all logs for this job.")
@click.confirmation_option(prompt='Are you sure you want to delete these logs? This cannot be undone.')
@click.pass_context
def cleanup_logs(ctx, job_id, before, all):
    """
    Delete execution logs for a specific job.
    """
    if not before and not all:
        click.echo("Error: You must specify either --before or --all.", err=True)
        return
    if before and all:
        click.echo("Error: Cannot use --before and --all together.", err=True)
        return

    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        db_path = config.get("settings", {}).get("db_path")
        if not db_path:
            click.echo("Error: 'db_path' not defined in [settings]. Cannot clean logs.", err=True)
            sys.exit(1)
        # Initialize DB for writing
        core_init_db(db_path)
    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True)
        sys.exit(1)

    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before)
        except ValueError:
            click.echo("Error: Invalid format for --before timestamp. Use ISO format (YYYY-MM-DD HH:MM:SS).", err=True)
            return

    click.echo(f"Attempting to delete logs for job '{job_id}'{' before ' + before if before else ' (all logs)'}...")

    try:
        # Use the core database function
        deleted_count = delete_job_logs(job_id, before_timestamp=before_dt if not all else None)

        if deleted_count >= 0:
            click.echo(f"Successfully deleted {deleted_count} log entries.")
        else:
            click.echo("An error occurred during log deletion. Check logs.", err=True)

    except Exception as e:
        click.echo(f"An error occurred during log cleanup: {e}", err=True)


@cli.command("reload-config")
@click.pass_context
def reload_config(ctx):
    """
    Signal the running daemon to reload the configuration file.
    (Requires IPC mechanism - currently not implemented).
    """
    # This command cannot directly modify the running daemon's state easily.
    # Options:
    # 1. Signal: Send a specific signal (e.g., SIGHUP) to the daemon PID. The daemon's signal handler reloads config.
    # 2. File Watcher: Daemon watches config file for changes (less common for explicit reload).
    # 3. IPC: Use sockets, DBus, etc., for the CLI to send a 'reload' command to the daemon.

    # Implementing Option 1 (Signal - SIGHUP):
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path)
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file:
             click.echo("Error: 'pid_file' not defined in [settings]. Cannot find daemon PID.", err=True)
             sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration to find PID file: {e}", err=True)
        sys.exit(1) # Cannot proceed without PID file path

    pid = read_pid(pid_file)
    if not pid or not is_process_running(pid):
        click.echo("Scheduler daemon is not running. Cannot reload configuration.", err=True)
        return

    click.echo(f"Sending SIGHUP signal to scheduler process PID {pid} to trigger configuration reload...")
    try:
        os.kill(pid, signal.SIGHUP)
        click.echo("SIGHUP signal sent. Check daemon logs to confirm reload.")
        # Need to add SIGHUP handler in core/scheduler_logic.py:start_scheduler_process
    except ProcessLookupError:
        click.echo(f"Error: Process with PID {pid} not found.", err=True)
        remove_pid(pid_file) # Clean up stale PID
    except PermissionError:
        click.echo(f"Error: Permission denied to signal process PID {pid}. Try with sudo?", err=True)
    except Exception as e:
        click.echo(f"An error occurred while sending signal: {e}", err=True)


# --- Main Execution ---
if __name__ == "__main__":
    cli(obj={}) # Pass initial context object
