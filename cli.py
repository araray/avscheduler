# cli.py

"""
Command Line Interface for managing the AVScheduler daemon, jobs, and logs.

Provides commands to start/stop/restart/status check the scheduler daemon,
manage job definitions in the configuration file, view execution logs,
and manually trigger job runs.
"""

import os
import sys
import signal
import toml
import click
import logging
from datetime import datetime
from subprocess import Popen
from tabulate import tabulate
from threading import Thread # Needed for foreground web start

# Adjust path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    # Core components
    from core.config_loader import load_config # *** IMPORT FROM NEW LOCATION ***
    from core.scheduler_logic import (
        start_scheduler_process, # Core scheduler loop
        write_pid, remove_pid, read_pid, is_process_running,
        add_or_update_job_in_scheduler, remove_job_from_scheduler,
        execute_job_command,
        scheduler as global_scheduler, # Global scheduler instance
        shutdown_scheduler # Import shutdown function
    )
    from core.database import (
        init_db as core_init_db,
        get_latest_job_log, get_job_logs, delete_job_logs,
        JobExecutionLog,
        get_session as core_get_session
    )
    # Utils
    from utils import get_valid_directory
    # Web factory (optional import)
    try:
        from web import create_app
    except ImportError as e:
        # Log warning but allow CLI to function without web parts if needed
        logging.warning(f"Could not import Flask app factory (web.create_app): {e}. Web UI will not start.")
        create_app = None
except ImportError as e:
    # Print detailed error for debugging imports
    print(f"Error importing core modules in cli.py: {e}", file=sys.stderr)
    print("Ensure the project structure is correct and PYTHONPATH is set if needed.", file=sys.stderr)
    # Also log the error if logging is already configured or can be minimally configured
    try:
        # Basic logging config for startup errors
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s [%(levelname)s] [CLI] %(message)s')
        logging.critical(f"Error importing core modules in cli.py: {e}", exc_info=True)
    except Exception:
        pass # Avoid errors during error handling
    sys.exit(1)


# Logging setup for CLI operations (separate from daemon logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [CLI] %(message)s')
logger = logging.getLogger(__name__) # Get logger specific to this module

# Config path helper
def resolve_config_path(ctx, param, value):
    """Click callback to resolve the default configuration file path."""
    if value: return value
    try:
        base_dir = get_valid_directory()
        default_path = os.path.join(base_dir or project_root, "config.toml")
        # Use logger from the module scope
        logger.debug(f"Using default config path: {default_path}")
        return default_path
    except Exception as e:
        logger.error(f"Error determining default config path: {e}")
        return os.path.join(project_root, "config.toml")

# --- CLI Group ---
@click.group(help="AVScheduler CLI: Manage the scheduler daemon, jobs, and logs.")
@click.option(
    "--config", "-c",
    type=click.Path(dir_okay=False), # Allow non-existent for add-job? Check logic there.
    callback=resolve_config_path,
    help="Path to the TOML configuration file."
)
@click.pass_context
def cli(ctx, config):
    """Main CLI group for AVScheduler."""
    ctx.ensure_object(dict)
    ctx.obj['CONFIG_PATH'] = config
    logger.debug(f"CLI using configuration file: {config}")


# --- Web UI Start Helper (for foreground mode) ---
def start_web_ui_in_thread(config: dict, scheduler_instance):
    """Starts the Flask app in a daemon thread if Flask is available."""
    if create_app is None:
        logger.warning("Flask app factory (web.create_app) not available. Cannot start web UI.")
        return None

    web_host = config.get("web_server", {}).get("host", "127.0.0.1")
    web_port = config.get("web_server", {}).get("port", 5000)

    def run_flask():
        """Target function for the Flask thread."""
        try:
            flask_app = create_app(scheduler_config=config, scheduler_instance=scheduler_instance)
            logger.info(f"Starting Flask web server on http://{web_host}:{web_port}...")
            # Run Flask's development server (suitable for this use case)
            # use_reloader=False is crucial when run within another managed process/thread
            flask_app.run(host=web_host, port=web_port, debug=False, use_reloader=False)
            logger.info("Flask web server thread finished.") # Should only happen on error/shutdown
        except Exception as e:
            logger.error(f"Flask web server thread failed: {e}", exc_info=True)

    # Create and start the daemon thread
    flask_thread = Thread(target=run_flask, daemon=True, name="FlaskWebServerThread")
    flask_thread.start()
    logger.info("Flask web server thread started.")
    return flask_thread


# --- Daemon Commands ---
@cli.command()
@click.option("--foreground", is_flag=True, default=True, help="Run the scheduler in the foreground (this is the default).")
@click.pass_context
def start(ctx, foreground):
    """
    Starts the AVScheduler core process (including jobs and web UI).

    This command runs the scheduler in the FOREGROUND by default.
    It handles PID file management and signal trapping (Ctrl+C, TERM, HUP).

    For background execution (true daemonization), it is strongly recommended
    to use a process manager like systemd, supervisor, or similar tools.
    Configure the process manager to run this 'start' command.
    """
    if not foreground:
         # This option is kept mainly for compatibility/clarity, but foreground is the only mode.
         click.echo("Note: Scheduler runs in the foreground. Use a process manager for background execution.", err=True)
         # foreground = True # Already defaults to True

    config_path = ctx.obj['CONFIG_PATH']
    config = None
    try:
        # 1. Load Config
        config = load_config(config_path) # Uses load_config from core.config_loader now
        pid_file = config.get("settings", {}).get("pid_file")
        db_path = config.get("settings", {}).get("db_path")
        if not pid_file or not db_path:
            click.echo("Error: 'pid_file' and 'db_path' must be defined in [settings].", err=True)
            sys.exit(1)

        # 2. Check if running via PID file
        pid = read_pid(pid_file)
        if pid and is_process_running(pid):
            click.echo(f"Scheduler appears to be already running with PID {pid} (PID file: {pid_file}).")
            return
        elif pid:
            click.echo(f"Warning: Found stale PID file '{pid_file}' for PID {pid}. Removing it.")
            remove_pid(pid_file)

        click.echo("Starting the scheduler...")
        click.echo("Running in foreground. Press Ctrl+C to stop.")

        # 3. Initialize DB (ensures tables exist)
        logger.info(f"Initializing database: {db_path}")
        core_init_db(db_path)

        # 4. Start Web UI Thread (if Flask is available)
        logger.info("Attempting to start Web UI thread...")
        web_thread = start_web_ui_in_thread(config, global_scheduler)
        if web_thread:
             logger.info("Web UI thread initiated.")
        else:
             logger.warning("Web UI thread could not be started (Flask/web dependencies might be missing).")

        # 5. Start Core Scheduler Process (this call blocks until terminated)
        logger.info("Starting AVScheduler core process...")
        start_scheduler_process(config) # This now blocks until signal

    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found at '{config_path}'", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
         # This is caught if Ctrl+C is pressed while the CLI command itself is running,
         # before start_scheduler_process takes over signal handling.
         click.echo("\nScheduler start interrupted by user (Ctrl+C).")
         sys.exit(0)
    except Exception as e:
        # Catch unexpected errors during startup sequence
        click.echo(f"Scheduler failed to start: {e}", err=True)
        logger.critical(f"Scheduler failed to start: {e}", exc_info=True) # Log full traceback
        # Attempt cleanup if PID file might have been created
        if config: # Check if config was loaded before error
             pid_file = config.get("settings", {}).get("pid_file")
             # Only remove PID if it exists and belongs to the current failed process
             if pid_file and read_pid(pid_file) == os.getpid():
                 remove_pid(pid_file)
        sys.exit(1)


@cli.command()
@click.pass_context
def stop(ctx):
    """
    Stop the running scheduler daemon process by sending SIGTERM to its PID.
    Reads the PID from the file specified in the configuration.
    """
    config_path = ctx.obj['CONFIG_PATH']
    pid_file = None
    try:
        # Load config primarily to find the PID file path
        config = load_config(config_path) # Use new loader
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file:
             click.echo("Error: 'pid_file' not defined in [settings]. Cannot determine process PID.", err=True)
             sys.exit(1)
    except FileNotFoundError:
        # Attempt to find PID file even if config is missing (best effort)
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

    # Read PID from the resolved file path
    pid = read_pid(pid_file)
    if not pid:
        click.echo(f"Scheduler not running (PID file '{pid_file}' not found or empty).")
        return

    # Check if the process actually exists
    if not is_process_running(pid):
        click.echo(f"Scheduler not running (process PID {pid} not found). Removing stale PID file '{pid_file}'.")
        remove_pid(pid_file) # Clean up stale file
        return

    # Attempt to stop the process
    click.echo(f"Stopping scheduler process with PID {pid} by sending SIGTERM...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly to allow graceful shutdown
        import time
        for _ in range(5): # Wait up to 5 seconds
             if not is_process_running(pid):
                 click.echo(f"Scheduler process {pid} stopped gracefully.")
                 # The daemon should remove its own PID file on successful shutdown via signal handler.
                 # Avoid removing it here to prevent race conditions.
                 return
             time.sleep(1)
        # If still running after timeout
        click.echo(f"Scheduler process {pid} did not stop gracefully after 5s. It might be stuck.", err=True)
        click.echo(f"Consider checking logs or using 'kill -9 {pid}' manually if necessary.", err=True)

    except ProcessLookupError:
        # Process already exited between check and kill
        click.echo(f"Error: Process with PID {pid} not found (already stopped?). Removing stale PID file.")
        if os.path.exists(pid_file): remove_pid(pid_file) # Clean up if possible
    except PermissionError:
        click.echo(f"Error: Permission denied to send signal to process PID {pid}. Try with sudo?", err=True)
    except Exception as e:
        click.echo(f"An error occurred while stopping the process: {e}", err=True)


@cli.command()
@click.pass_context
def status(ctx):
    """
    Check if the scheduler daemon process is running based on the PID file.
    Verifies if the PID file exists and if the process ID within it is active.
    """
    config_path = ctx.obj['CONFIG_PATH']
    pid_file = None
    try:
        # Load config to get PID file path
        config = load_config(config_path) # Use new loader
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file:
             click.echo("Error: 'pid_file' not defined in [settings]. Cannot determine status.", err=True)
             sys.exit(1)
    except FileNotFoundError:
        # Try default path if config missing
        click.echo(f"Warning: Config file '{config_path}' not found. Status check might be inaccurate.", err=True)
        try:
            base_dir = get_valid_directory()
            pid_file = os.path.join(base_dir or project_root, "logs", "avscheduler.pid")
        except Exception:
            click.echo("Error: Cannot determine PID file path without configuration.", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    # Check PID file and process status
    pid = read_pid(pid_file)
    if not pid:
        click.echo(f"Scheduler is stopped (PID file '{pid_file}' not found or empty).")
        return
    if is_process_running(pid):
        click.echo(f"Scheduler is running with PID {pid} (PID file: {pid_file}).")
    else:
        # PID file exists but process doesn't
        click.echo(f"Scheduler is stopped (stale PID file '{pid_file}' found for PID {pid}, process not running).")
        # Optionally offer to remove the stale file:
        # if click.confirm(f"Remove stale PID file '{pid_file}'?"):
        #     remove_pid(pid_file)


@cli.command()
@click.pass_context
def restart(ctx):
    """
    Stop the scheduler daemon (if running) and then start it again.
    Note: The scheduler will start in the foreground after restart.
    """
    click.echo("Attempting to restart the scheduler...")
    # Invoke the 'stop' command first
    ctx.invoke(stop)
    # Wait a moment to ensure the process has time to exit and release resources
    import time
    click.echo("Waiting 2 seconds before starting...")
    time.sleep(2)
    # Invoke the 'start' command
    click.echo("Starting scheduler again (in foreground)...")
    # The 'start' command now defaults to foreground
    ctx.invoke(start)


# --- Job Management Commands ---

@cli.command("list-jobs")
@click.pass_context
def list_jobs(ctx):
    """
    List all jobs defined in the configuration file.
    Also shows the status of the last execution based on database logs.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path) # Use new loader
        db_path = config.get("settings", {}).get("db_path")
        if not db_path: raise ValueError("'db_path' not defined in [settings]")
        # Initialize DB connection for reading logs
        core_init_db(db_path)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True)
        sys.exit(1)

    jobs = config.get("jobs", {})
    if not jobs:
        click.echo("No jobs found in the configuration file.")
        return

    results_table = []
    headers = ["Job ID", "Type", "Schedule", "Condition", "Last Run", "Last Exit", "Last Duration (s)", "Next Run (Live*)"]
    click.echo("Fetching job status from configuration and database logs...")
    click.echo("(*) Next Run Time requires Inter-Process Communication (IPC) with the running daemon, which is not currently implemented in the CLI.")

    # Iterate through jobs defined in the config file
    for job_id, job_config in jobs.items():
        # Get the latest log entry for this job from the database
        latest_log = get_latest_job_log(job_id)

        # Format schedule information for display
        schedule_type = job_config.get("schedule_type", "N/A")
        if schedule_type == "cron": schedule_info = f"Cron: {job_config.get('schedule', 'N/A')}"
        elif schedule_type == "interval": schedule_info = f"Interval: {job_config.get('interval_seconds', 'N/A')}s"
        elif schedule_type == "date": schedule_info = f"Date: {job_config.get('run_date', 'N/A')}"
        else: schedule_info = "N/A"

        # Add row to the results table
        results_table.append([
            job_id,
            job_config.get("type", "N/A"),
            schedule_info,
            job_config.get("condition", "N/A"),
            # Format log data if available
            latest_log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_log else "N/A",
            latest_log.exit_code if latest_log else "N/A",
            f"{latest_log.execution_time:.3f}" if latest_log else "N/A",
            "N/A" # Placeholder for live next run time
        ])

    # Sort the table by Job ID for consistent output
    results_table.sort(key=lambda row: row[0])
    # Print the table using tabulate
    click.echo(tabulate(results_table, headers=headers, tablefmt="grid"))


@cli.command("run-job")
@click.argument("job_id")
@click.option("--timeout", type=int, help="Optional execution timeout in seconds.")
@click.pass_context
def run_single_job(ctx, job_id, timeout):
    """
    Manually execute a specific job by its ID immediately.
    This bypasses the job's schedule and any defined conditions.
    Logs the execution result to the database.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        # Load config to get job details and DB path
        config = load_config(config_path) # Use new loader
        db_path = config.get("settings", {}).get("db_path")
        if not db_path: raise ValueError("'db_path' not defined")
        # Initialize DB for logging the manual run
        core_init_db(db_path)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True); sys.exit(1)

    # Find the job configuration
    job_config = config.get("jobs", {}).get(job_id)
    if not job_config:
        click.echo(f"Error: Job '{job_id}' not found in configuration.", err=True); return

    # Get interpreter and command details
    interpreter_type = job_config.get("type")
    interpreter_path = config.get("interpreters", {}).get(interpreter_type)
    command = job_config.get("command")
    env_file = job_config.get("env_file")

    # Validate necessary details
    if not interpreter_path:
        click.echo(f"Error: Interpreter type '{interpreter_type}' for job '{job_id}' not defined in [interpreters].", err=True); return
    if not command:
        click.echo(f"Error: Job '{job_id}' has no command defined.", err=True); return

    # Execute the job command using the core function
    click.echo(f"Manually running job '{job_id}'...")
    exit_code, exec_time, stdout, stderr = execute_job_command(
        job_id, interpreter_path, command, env_file, timeout
    )

    # Display results
    click.echo(f"\n--- Job '{job_id}' Manual Execution Finished ---")
    click.echo(f"Exit Code: {exit_code}")
    click.echo(f"Duration: {exec_time:.3f}s")
    if stdout: click.echo(f"--- STDOUT ---\n{stdout.strip()}")
    if stderr: click.echo(f"--- STDERR ---\n{stderr.strip()}")

    # Log the manual execution to the database
    from core.database import log_job_execution
    log_job_execution(job_id, exit_code, exec_time, stdout, stderr)
    click.echo("Execution result logged to database.")


@cli.command("add-job")
@click.argument("job_id")
@click.option("--type", required=True, prompt="Job Type (e.g., PYTHON, BASH)", help="Interpreter type (must exist in [interpreters])")
@click.option("--schedule-type", required=True, type=click.Choice(['cron', 'interval', 'date']), prompt=True, help="Type of schedule trigger.")
# Conditional options based on schedule_type (validation done in code)
@click.option("--schedule", help="Cron schedule string (e.g., '0 * * * *'). Required if schedule-type=cron.")
@click.option("--interval-seconds", type=int, help="Interval in seconds. Required if schedule-type=interval.")
@click.option("--run-date", help="Specific run date/time (ISO format: YYYY-MM-DD HH:MM:SS). Required if schedule-type=date.")
@click.option("--command", required=True, prompt=True, help="Command string for the job to execute.")
@click.option("--condition", help="Optional execution condition string (e.g., 'other_job.last_run_successful').")
@click.option("--env-file", type=click.Path(exists=True, dir_okay=False, resolve_path=True), help="Optional path to a file containing environment variables.")
@click.option("--timeout", type=int, help="Optional execution timeout in seconds for this job.")
@click.pass_context
def add_job(ctx, job_id, type, schedule_type, schedule, interval_seconds, run_date, command, condition, env_file, timeout):
    """
    Add a new job definition to the configuration file.

    This command modifies the config file directly. For the changes
    to take effect in the running scheduler, you must either run the
    'reload-config' command or restart the scheduler daemon.
    """
    config_path = ctx.obj['CONFIG_PATH']
    config = {}
    try:
        # Load existing config or prepare to create a new one
        config = load_config(config_path) # Use new loader
    except FileNotFoundError:
        click.echo(f"Info: Config file '{config_path}' not found. Creating a new structure.")
        # Define basic structure for a new file
        config = {"settings": {}, "interpreters": {}, "jobs": {}, "web_server": {}}
        # Attempt to add sensible defaults if possible
        try:
            base_dir = get_valid_directory()
            config['settings']['db_path'] = os.path.join(base_dir or project_root, "jobs.db")
            config['settings']['pid_file'] = os.path.join(base_dir or project_root, "logs", "avscheduler.pid")
            config['web_server']['host'] = "127.0.0.1"
            config['web_server']['port'] = 5000
            click.echo("Added default paths for db_path, pid_file, and web_server.")
        except Exception:
            click.echo("Warning: Could not determine default paths for new config.", err=True)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True); sys.exit(1)

    # Validate interpreter type exists in config
    if type not in config.get("interpreters", {}):
        click.echo(f"Error: Interpreter type '{type}' is not defined in the [interpreters] section of '{config_path}'. Add it first.", err=True); return

    # Ensure 'jobs' section exists and check for duplicates
    jobs = config.setdefault("jobs", {})
    if job_id in jobs:
        click.echo(f"Error: Job ID '{job_id}' already exists in the configuration.", err=True); return

    # Build the new job dictionary with validation
    new_job = {"type": type, "schedule_type": schedule_type, "command": command}
    # Validate schedule details based on type
    if schedule_type == "cron":
        if not schedule: click.echo("Error: --schedule is required for schedule-type 'cron'.", err=True); return
        # Basic cron validation could be added here if desired
        new_job["schedule"] = schedule
    elif schedule_type == "interval":
        if interval_seconds is None: click.echo("Error: --interval-seconds is required for schedule-type 'interval'.", err=True); return
        if interval_seconds <= 0: click.echo("Error: --interval-seconds must be positive.", err=True); return
        new_job["interval_seconds"] = interval_seconds
    elif schedule_type == "date":
        if not run_date: click.echo("Error: --run-date is required for schedule-type 'date'.", err=True); return
        try:
            # Validate ISO format
            datetime.fromisoformat(run_date)
        except ValueError:
            click.echo("Error: Invalid format for --run-date. Use ISO format (YYYY-MM-DD HH:MM:SS).", err=True); return
        new_job["run_date"] = run_date

    # Add optional fields if provided
    if condition: new_job["condition"] = condition
    if env_file: new_job["env_file"] = env_file # Path existence checked by Click
    if timeout is not None:
        if timeout <= 0: click.echo("Error: --timeout must be positive if provided.", err=True); return
        new_job["timeout_seconds"] = timeout

    # Add the job to the config structure
    jobs[job_id] = new_job

    # Write the updated configuration back to the file
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' added successfully to configuration file '{config_path}'.")
        click.echo("IMPORTANT: Run 'reload-config' or restart the daemon for these changes to take effect.")
    except IOError as e:
        click.echo(f"Error: Failed to write configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


@cli.command("edit-job")
@click.argument("job_id")
# Options for fields that can be edited
@click.option("--type", help="New interpreter type (must exist in [interpreters]).")
@click.option("--schedule-type", type=click.Choice(['cron', 'interval', 'date']), help="Change the schedule type.")
@click.option("--schedule", help="New cron schedule string (use with schedule-type=cron).")
@click.option("--interval-seconds", type=int, help="New interval in seconds (use with schedule-type=interval).")
@click.option("--run-date", help="New specific run date/time (ISO format; use with schedule-type=date).")
@click.option("--command", help="New command string to execute.")
@click.option("--condition", help="New execution condition string (use '' to remove condition).")
@click.option("--env-file", help="New path to an environment file (use '' to remove env file).")
@click.option("--timeout", type=int, help="New execution timeout in seconds (use -1 to remove timeout).")
@click.pass_context
def edit_job(ctx, job_id, **kwargs):
    """
    Edit properties of an existing job in the configuration file.

    Allows modification of various job parameters like schedule, command,
    condition, etc. Only provided options will be changed.
    Use empty string ('') for --condition or --env-file to remove them.
    Use -1 for --timeout to remove it.

    Requires manual 'reload-config' or daemon restart to take effect.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path) # Use new loader
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True); sys.exit(1)

    jobs = config.get("jobs", {})
    if job_id not in jobs:
        click.echo(f"Error: Job '{job_id}' not found in the configuration.", err=True); return

    job_data = jobs[job_id] # Get the dictionary for the job
    updated_fields_count = 0

    # Iterate through the options provided by the user
    for key, value in kwargs.items():
        if value is None: continue # Skip options that were not passed

        # Map the Click option name to the TOML key name if different
        field_name = key if key != "timeout" else "timeout_seconds"

        # Handle special values for removing fields
        if field_name in ["condition", "env_file"] and value == '':
            if job_data.pop(field_name, None) is not None: # Remove if exists
                click.echo(f"Removing field '{field_name}' for job '{job_id}'.")
                updated_fields_count += 1
            else:
                click.echo(f"Field '{field_name}' not present for job '{job_id}', cannot remove.")
        elif field_name == "timeout_seconds" and value == -1:
            if job_data.pop(field_name, None) is not None: # Remove if exists
                click.echo(f"Removing timeout for job '{job_id}'.")
                updated_fields_count += 1
            else:
                click.echo(f"Timeout not set for job '{job_id}', cannot remove.")
        else:
            # Handle normal updates/additions
            # --- Perform Validations ---
            if field_name == "type" and value not in config.get("interpreters", {}):
                 click.echo(f"Error: Interpreter type '{value}' is not defined in [interpreters]. Skipping update.", err=True); continue
            if field_name == "schedule_type":
                 # When changing schedule type, clear out potentially conflicting old schedule fields
                 job_data.pop("schedule", None); job_data.pop("interval_seconds", None); job_data.pop("run_date", None)
                 click.echo("Cleared previous schedule fields due to schedule_type change.")
            if field_name == "run_date":
                 try: datetime.fromisoformat(value)
                 except (ValueError, TypeError): click.echo(f"Error: Invalid format for --run-date '{value}'. Use ISO format. Skipping update.", err=True); continue
            if field_name == "interval_seconds" and value <= 0:
                 click.echo("Error: --interval-seconds must be positive. Skipping update.", err=True); continue
            if field_name == "timeout_seconds" and value <= 0:
                 click.echo("Error: --timeout must be positive. Skipping update.", err=True); continue
            # --- Apply Update ---
            if job_data.get(field_name) != value: # Check if value actually changed
                job_data[field_name] = value
                click.echo(f"Updating field '{field_name}' for job '{job_id}'.")
                updated_fields_count += 1
            else:
                click.echo(f"Field '{field_name}' already has the specified value.")


    if updated_fields_count == 0:
        click.echo("No changes specified or values matched existing configuration.")
        return

    # --- Final Validation after all changes ---
    # Check if the schedule configuration is consistent with the final schedule_type
    final_schedule_type = job_data.get("schedule_type")
    schedule_valid = True
    if final_schedule_type == "cron" and "schedule" not in job_data:
        click.echo("Error: Job configuration invalid - 'schedule' field is required for schedule_type 'cron'.", err=True); schedule_valid = False
    elif final_schedule_type == "interval" and "interval_seconds" not in job_data:
        click.echo("Error: Job configuration invalid - 'interval_seconds' field is required for schedule_type 'interval'.", err=True); schedule_valid = False
    elif final_schedule_type == "date" and "run_date" not in job_data:
        click.echo("Error: Job configuration invalid - 'run_date' field is required for schedule_type 'date'.", err=True); schedule_valid = False

    if not schedule_valid:
        click.echo("Configuration was not saved due to validation errors. Please correct the options.", err=True)
        return

    # Write updated config back to file
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' updated successfully in configuration file '{config_path}'.")
        click.echo("IMPORTANT: Run 'reload-config' or restart the daemon for these changes to take effect.")
    except IOError as e:
        click.echo(f"Error: Failed to write configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


@cli.command("delete-job")
@click.argument("job_id")
@click.confirmation_option(prompt='Are you sure you want to permanently delete this job definition from the configuration file?')
@click.pass_context
def delete_job(ctx, job_id):
    """
    Delete a job definition from the configuration file.

    This action modifies the config file. The change will only affect the
    running scheduler after a 'reload-config' or a daemon restart.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        config = load_config(config_path) # Use new loader
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True); sys.exit(1)

    jobs = config.get("jobs", {})
    if job_id not in jobs:
        click.echo(f"Error: Job '{job_id}' not found in the configuration.", err=True); return

    # Perform deletion
    del jobs[job_id]

    # Write the modified configuration back
    try:
        with open(config_path, "w") as f:
            toml.dump(config, f)
        click.echo(f"Job '{job_id}' deleted successfully from configuration file '{config_path}'.")
        click.echo("IMPORTANT: Run 'reload-config' or restart the daemon for this change to take effect.")
    except IOError as e:
        click.echo(f"Error: Failed to write configuration file '{config_path}': {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred while writing the configuration: {e}", err=True)


# --- Log Management Commands ---

@cli.command("view-logs")
@click.option("--job-id", default=None, help="Filter logs to show only for a specific Job ID.")
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum number of log entries to retrieve and display.")
@click.pass_context
def view_logs(ctx, job_id, limit):
    """
    View job execution logs stored in the database.
    Logs are displayed most recent first. Includes stdout/stderr snippets.
    """
    config_path = ctx.obj['CONFIG_PATH']
    try:
        # Load config to get DB path
        config = load_config(config_path) # Use new loader
        db_path = config.get("settings", {}).get("db_path")
        if not db_path: raise ValueError("'db_path' not defined")
        # Initialize DB for reading
        core_init_db(db_path)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True); sys.exit(1)

    click.echo(f"Fetching logs{' for job ' + job_id if job_id else ''} (limit {limit})...")
    try:
        # Get DB session
        session = core_get_session()
        if not session: raise RuntimeError("DB session unavailable")

        # Build query
        query = session.query(JobExecutionLog)
        if job_id:
            query = query.filter(JobExecutionLog.job_id == job_id)
        # Order by timestamp descending and apply limit
        logs = query.order_by(JobExecutionLog.timestamp.desc()).limit(limit).all()
        session.close() # Close session after query

        if not logs:
            click.echo("No logs found matching the criteria."); return

        # Prepare data for tabulation
        headers = ["Log ID", "Job ID", "Timestamp", "Exit", "Duration", "Output Snippet"]
        table_data = []
        for log in logs:
            # Create a concise snippet of stdout or stderr
            output_snippet = ""
            if log.stderr:
                output_snippet = f"STDERR: {log.stderr[:50]}" # Take first 50 chars
                if len(log.stderr) > 50: output_snippet += "..."
            elif log.stdout:
                 output_snippet = f"STDOUT: {log.stdout[:50]}"
                 if len(log.stdout) > 50: output_snippet += "..."

            table_data.append([
                log.id, log.job_id, log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.exit_code, f"{log.execution_time:.3f}s", output_snippet
            ])
        # Print the formatted table
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))

    except Exception as e:
        click.echo(f"Error retrieving or displaying logs: {e}", err=True)
        logger.error("Error retrieving logs", exc_info=True) # Log traceback


@cli.command("cleanup-logs")
@click.argument("job_id")
@click.option("--before", help="Delete logs with timestamp strictly BEFORE this date/time (ISO format: YYYY-MM-DD HH:MM:SS).")
@click.option("--all", is_flag=True, help="Delete ALL logs for the specified job.")
@click.confirmation_option(prompt='Are you sure you want to permanently delete these log entries? This action cannot be undone.')
@click.pass_context
def cleanup_logs(ctx, job_id, before, all):
    """
    Delete execution logs for a specific job from the database.

    Use EITHER --before OR --all to specify which logs to delete.
    Requires confirmation before proceeding.
    """
    # Validate options
    if not before and not all:
        click.echo("Error: You must specify either --before OR --all.", err=True); return
    if before and all:
        click.echo("Error: Cannot use --before and --all together. Choose one.", err=True); return

    config_path = ctx.obj['CONFIG_PATH']
    try:
        # Load config for DB path
        config = load_config(config_path) # Use new loader
        db_path = config.get("settings", {}).get("db_path")
        if not db_path: raise ValueError("'db_path' not defined")
        # Initialize DB for writing (deletion)
        core_init_db(db_path)
    except Exception as e:
        click.echo(f"Error loading configuration or initializing DB: {e}", err=True); sys.exit(1)

    # Parse timestamp if provided
    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before)
        except ValueError:
            click.echo("Error: Invalid format for --before timestamp. Use ISO format (YYYY-MM-DD HH:MM:SS).", err=True); return

    # Perform deletion using the core function
    click.echo(f"Attempting to delete logs for job '{job_id}'{' before ' + before if before else ' (all logs)'}...")
    try:
        # Pass None for before_timestamp if --all is used
        deleted_count = delete_job_logs(job_id, before_timestamp=before_dt if not all else None)

        if deleted_count >= 0:
            click.echo(f"Successfully deleted {deleted_count} log entries.")
        else:
            # delete_job_logs returns -1 on error in current implementation
            click.echo("An error occurred during log deletion. Check application logs.", err=True)

    except Exception as e:
        # Catch potential errors from the delete function or DB interaction
        click.echo(f"An error occurred during log cleanup: {e}", err=True)
        logger.error(f"Error cleaning logs for job '{job_id}'", exc_info=True)


@cli.command("reload-config")
@click.pass_context
def reload_config(ctx):
    """
    Signal the running scheduler daemon to reload the configuration file.

    This sends a SIGHUP signal to the process identified by the PID file.
    The daemon must have a SIGHUP handler implemented (as in the current
    core.scheduler_logic) to actually reload the config and update jobs.
    """
    config_path = ctx.obj['CONFIG_PATH']
    pid_file = None
    try:
        # Load config only to find the PID file location
        config = load_config(config_path) # Use new loader
        pid_file = config.get("settings", {}).get("pid_file")
        if not pid_file: raise ValueError("'pid_file' not defined")
    except Exception as e:
        click.echo(f"Error loading configuration to find PID file: {e}", err=True); sys.exit(1)

    # Find the PID of the running daemon
    pid = read_pid(pid_file)
    if not pid or not is_process_running(pid):
        click.echo("Scheduler daemon does not appear to be running. Cannot send reload signal.", err=True); return

    # Send the SIGHUP signal
    click.echo(f"Sending SIGHUP signal to scheduler process PID {pid} to trigger configuration reload...")
    try:
        os.kill(pid, signal.SIGHUP)
        click.echo("SIGHUP signal sent successfully. Check daemon logs to confirm if the configuration was reloaded.")
    except ProcessLookupError:
        # Process died between check and signal send
        click.echo(f"Error: Process with PID {pid} not found (it may have terminated unexpectedly).", err=True)
        remove_pid(pid_file) # Clean up stale PID file
    except PermissionError:
        click.echo(f"Error: Permission denied to send signal to process PID {pid}. Try using sudo if necessary.", err=True)
    except Exception as e:
        # Catch other potential errors from os.kill
        click.echo(f"An error occurred while sending the SIGHUP signal: {e}", err=True)


# --- Main Execution Guard ---
if __name__ == "__main__":
    # Entry point when script is run directly
    # Pass an empty object for context initialization
    cli(obj={})
