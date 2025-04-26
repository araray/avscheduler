# core/scheduler_logic.py

"""
Core logic for the AVScheduler, including job execution, logging,
and interaction with the APScheduler instance and starting the web UI.
"""

import os
import toml
import logging
import signal
import sys
import time
from datetime import datetime
from subprocess import Popen, PIPE, TimeoutExpired
from typing import Dict, Any, Optional
from threading import Thread # Import Thread

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError

# Assuming database operations are now in core.database
from .database import init_db as core_init_db, log_job_execution
# Assuming condition evaluation is in core.conditions
from .conditions import evaluate_condition
# Import the Flask app factory
try:
    from web import create_app
except ImportError as e:
     # This might happen if web dependencies aren't installed, handle gracefully
     logging.warning(f"Could not import Flask app factory (web.create_app): {e}. Web UI will not start.")
     create_app = None


# Configure logging (consider moving to a central config later)
# Ensure logs directory exists relative to the project root or a configured path
# Corrected path assumption: logs dir relative to project root (where scheduler.py/cli.py are)
project_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logs_dir = os.path.join(project_root_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
log_file_path = os.path.join(logs_dir, "scheduler.log")

# Ensure logs can be written - consider file handler level setting
file_handler = logging.FileHandler(log_file_path, mode='a')
file_handler.setLevel(logging.INFO) # Set level for file handler if needed

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO) # Set level for console handler

logging.basicConfig(
    level=logging.DEBUG, # Set root logger level (can be overridden by handlers)
    handlers=[
        file_handler,
        stream_handler # Also log to console
    ],
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Global scheduler instance
# Consider making this part of a class or managing it via the application context (e.g., Flask app)
# For now, keep it global for simplicity, similar to the original structure.
scheduler = BackgroundScheduler(daemon=True) # Run scheduler thread as daemon

# --- Configuration Loading ---

def load_config(config_file: str) -> Dict[str, Any]:
    """
    Loads the TOML configuration file.

    Args:
        config_file: Path to the configuration file.

    Returns:
        A dictionary containing the loaded configuration.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        toml.TomlDecodeError: If the config file is invalid TOML.
        ValueError: If essential sections/keys are missing.
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file '{config_file}' not found.")

    logger.info(f"Loading configuration from: {config_file}")
    try:
        config = toml.load(config_file)
        # Store the path from where the config was loaded for potential use later (e.g., reload)
        config["_config_file_path"] = config_file
    except toml.TomlDecodeError as e:
        logger.error(f"Error decoding TOML configuration file '{config_file}': {e}")
        raise

    # --- Configuration Validation and Defaults ---
    if "settings" not in config:
        logger.warning("Config missing [settings] section, using defaults.")
        config["settings"] = {}
    if "db_path" not in config["settings"]:
        # Default DB path relative to config file's directory or project root
        default_db_path = os.path.join(os.path.dirname(config_file) or '.', "jobs.db")
        config["settings"]["db_path"] = default_db_path
        logger.info(f"Config missing 'db_path', defaulting to: {default_db_path}")
    if "pid_file" not in config["settings"]:
        # Default PID path relative to project root's logs dir
        default_pid_path = os.path.join(logs_dir, "avscheduler.pid")
        config["settings"]["pid_file"] = default_pid_path
        logger.info(f"Config missing 'pid_file', defaulting to: {default_pid_path}")

    if "interpreters" not in config:
        logger.warning("Config missing [interpreters] section. Jobs might fail.")
        config["interpreters"] = {}

    if "jobs" not in config:
        logger.warning("Config missing [jobs] section. No jobs to schedule.")
        config["jobs"] = {}

    if "web_server" not in config:
        logger.warning("Config missing [web_server] section, using defaults.")
        config["web_server"] = {}
    if "host" not in config["web_server"]:
        config["web_server"]["host"] = "127.0.0.1"
    if "port" not in config["web_server"]:
        config["web_server"]["port"] = 5000 # Default Flask port

    logger.info("Configuration loaded successfully.")
    return config

# --- PID File Management ---

def write_pid(pid_file: str):
    """
    Writes the current process PID to the specified PID file.
    Ensures the directory exists.
    """
    try:
        pid_dir = os.path.dirname(pid_file)
        if pid_dir and not os.path.exists(pid_dir):
            os.makedirs(pid_dir, exist_ok=True)
            logger.info(f"Created PID directory: {pid_dir}")

        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"Scheduler PID {os.getpid()} written to {pid_file}")
    except OSError as e:
        logger.error(f"Failed to write PID file '{pid_file}': {e}", exc_info=True)
        # Depending on severity, might want to exit or raise
    except Exception as e:
        logger.error(f"Unexpected error writing PID file '{pid_file}': {e}", exc_info=True)

def remove_pid(pid_file: str):
    """
    Removes the PID file if it exists.
    """
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
            logger.info(f"PID file {pid_file} removed.")
    except OSError as e:
        logger.error(f"Failed to remove PID file '{pid_file}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error removing PID file '{pid_file}': {e}", exc_info=True)

def read_pid(pid_file: str) -> Optional[int]:
    """Reads the PID from the PID file."""
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, "r") as f:
            pid_str = f.read().strip()
            if pid_str:
                return int(pid_str)
            else:
                logger.warning(f"PID file '{pid_file}' is empty.")
                return None
    except ValueError:
        logger.error(f"Invalid PID value found in '{pid_file}'.")
        return None
    except OSError as e:
        logger.error(f"Error reading PID file '{pid_file}': {e}")
        return None

def is_process_running(pid: int) -> bool:
    """Checks if a process with the given PID is running."""
    if pid <= 0:
        return False
    # Simple check using os.kill with signal 0 (doesn't actually kill)
    try:
        os.kill(pid, 0)
    except OSError:
        return False # No such process or permission error (assume not running)
    else:
        return True

# --- Job Execution ---

def execute_job_command(job_id: str, interpreter: str, command: str, env_file: Optional[str] = None, timeout_seconds: Optional[int] = None):
    """
    Executes the job's command in a subprocess and logs results.

    Args:
        job_id: The ID of the job being executed.
        interpreter: The path to the interpreter (e.g., /usr/bin/python3).
        command: The command string to execute.
        env_file: Optional path to a file containing environment variables.
        timeout_seconds: Optional timeout for the subprocess execution.
    """
    start_time = datetime.now()
    logger.info(f"Starting job '{job_id}' - Command: {interpreter} -c \"{command[:100]}{'...' if len(command) > 100 else ''}\"")

    # --- Environment Setup ---
    job_env = os.environ.copy()
    if env_file and os.path.exists(env_file):
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        job_env[key.strip()] = value.strip()
            logger.debug(f"Loaded environment variables for job '{job_id}' from: {env_file}")
        except Exception as e:
            logger.error(f"Failed to load env file '{env_file}' for job '{job_id}': {e}", exc_info=True)
            # Decide if this should be fatal for the job run
            # For now, log error and continue with default env

    # --- Subprocess Execution ---
    process = None
    stdout_str = None
    stderr_str = None
    exit_code = -1 # Default to error exit code

    try:
        # Use Popen for better control, especially with timeout
        process = Popen(
            [interpreter, "-c", command],
            stdout=PIPE,
            stderr=PIPE,
            env=job_env,
            text=True, # Decode stdout/stderr as text
            encoding='utf-8', # Specify encoding
            errors='replace' # Handle potential decoding errors
        )

        # Wait for process completion with optional timeout
        stdout_str, stderr_str = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
        logger.info(f"Job '{job_id}' finished with exit code: {exit_code}")

    except FileNotFoundError:
        logger.error(f"Interpreter '{interpreter}' not found for job '{job_id}'. Check config [interpreters].")
        stderr_str = f"Interpreter not found: {interpreter}"
        exit_code = -2 # Specific exit code for interpreter not found
    except TimeoutExpired:
        logger.warning(f"Job '{job_id}' timed out after {timeout_seconds} seconds. Terminating.")
        if process:
            process.terminate() # Try graceful termination first
            try:
                # Wait a bit more for termination
                stdout_str, stderr_str = process.communicate(timeout=5)
            except TimeoutExpired:
                logger.error(f"Job '{job_id}' did not terminate gracefully after timeout. Killing.")
                process.kill() # Force kill
                stdout_str, stderr_str = process.communicate() # Capture any final output
        stderr_str = (stderr_str or "") + "\nJob timed out and was terminated."
        exit_code = -3 # Specific exit code for timeout
    except Exception as e:
        logger.error(f"Error executing job '{job_id}': {e}", exc_info=True)
        stderr_str = (stderr_str or "") + f"\nExecution Error: {e}"
        exit_code = -4 # General execution error
    finally:
        if process and process.poll() is None: # Ensure process is cleaned up if communicate failed early
             process.kill()
             logger.warning(f"Force killed job '{job_id}' process due to unexpected state.")


    # --- Logging Results ---
    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()
    logger.info(f"Job '{job_id}' execution time: {execution_time:.3f} seconds")

    if stdout_str:
        logger.debug(f"Job '{job_id}' STDOUT:\n{stdout_str.strip()}")
    if stderr_str:
        logger.warning(f"Job '{job_id}' STDERR:\n{stderr_str.strip()}")

    # DB logging moved to wrapper `run_job_wrapper`.

    return exit_code, execution_time, stdout_str, stderr_str


def run_job_wrapper(job_id: str, config: Dict[str, Any]):
    """
    Wrapper function called by APScheduler.
    Loads job details, checks conditions, executes the job, and logs to DB.
    """
    logger.info(f"Scheduler triggered for job '{job_id}'")
    # Reload config within the job execution context? Or rely on the config passed at scheduling time?
    # Passing config at scheduling time is simpler but won't reflect live config changes
    # unless the job is rescheduled by reload_config. Let's stick with passed config for now.
    job_config = config.get("jobs", {}).get(job_id)
    if not job_config:
        logger.error(f"Job configuration for '{job_id}' not found in passed config. Skipping.")
        # Cannot log to DB if config is missing db_path
        return

    interpreter_type = job_config.get("type")
    interpreter_path = config.get("interpreters", {}).get(interpreter_type)
    command = job_config.get("command")
    condition_str = job_config.get("condition")
    env_file = job_config.get("env_file")
    db_path = config.get("settings", {}).get("db_path")
    timeout = job_config.get("timeout_seconds") # Optional timeout per job

    if not interpreter_path:
        logger.error(f"Interpreter type '{interpreter_type}' for job '{job_id}' not defined in [interpreters]. Skipping.")
        if db_path: log_job_execution(job_id, -5, 0, stderr="Interpreter type not configured") # Log config error
        return
    if not command:
        logger.error(f"Job '{job_id}' has no command defined. Skipping.")
        if db_path: log_job_execution(job_id, -6, 0, stderr="Job command not defined") # Log config error
        return
    if not db_path:
         logger.error(f"Database path not configured in [settings]. Cannot log or check conditions for job '{job_id}'. Skipping.")
         # Cannot log this error to DB itself!
         return

    # --- Condition Check ---
    if condition_str:
        logger.debug(f"Checking condition for job '{job_id}': {condition_str}")
        try:
            condition_met = evaluate_condition(condition_str, db_path, job_id)
            if not condition_met:
                logger.info(f"Skipping job '{job_id}' because its condition is not met: {condition_str}")
                # Optionally log skipped runs? For now, just log to scheduler log.
                return
            else:
                 logger.debug(f"Condition met for job '{job_id}'.")
        except Exception as e:
            logger.error(f"Error evaluating condition for job '{job_id}': {e}. Skipping job.", exc_info=True)
            # Log condition evaluation error to DB
            log_job_execution(job_id, -7, 0, stderr=f"Condition evaluation error: {e}")
            return

    # --- Execute Job ---
    exit_code, exec_time, stdout, stderr = execute_job_command(
        job_id, interpreter_path, command, env_file, timeout
    )

    # --- Log to Database ---
    log_job_execution(job_id, exit_code, exec_time, stdout, stderr)


# --- Scheduler Management ---

def add_or_update_job_in_scheduler(job_id: str, job_config: Dict[str, Any], config: Dict[str, Any]):
    """
    Adds a new job or updates an existing one in the APScheduler instance.

    Args:
        job_id: The unique ID for the job.
        job_config: The configuration dictionary for the job.
        config: The global application configuration (needed for the wrapper).
    """
    schedule_type = job_config.get("schedule_type", "cron") # Default to cron
    trigger = None

    try:
        if schedule_type == "cron":
            cron_schedule = job_config.get("schedule")
            if not cron_schedule:
                raise ValueError("Missing 'schedule' for cron job.")
            trigger = CronTrigger.from_crontab(cron_schedule, timezone='UTC') # Consider timezone
        elif schedule_type == "interval":
            interval_seconds = job_config.get("interval_seconds")
            if interval_seconds is None:
                raise ValueError("Missing 'interval_seconds' for interval job.")
            trigger = IntervalTrigger(seconds=int(interval_seconds), timezone='UTC')
        elif schedule_type == "date":
            run_date_str = job_config.get("run_date")
            if not run_date_str:
                 raise ValueError("Missing 'run_date' for date job.")
            run_date = datetime.fromisoformat(run_date_str) # Expect ISO format
            trigger = DateTrigger(run_date=run_date, timezone='UTC')
        else:
            raise ValueError(f"Unsupported schedule_type: {schedule_type}")

        # Add or modify the job
        scheduler.add_job(
            func=run_job_wrapper,
            args=[job_id, config], # Pass job_id and the *full config* to the wrapper
            trigger=trigger,
            id=job_id,
            name=job_config.get("name", job_id), # Use job_id as name if not provided
            replace_existing=True, # Update if job_id already exists
            misfire_grace_time=job_config.get("misfire_grace_time", 60), # Optional: seconds job can start late
            coalesce=job_config.get("coalesce", True), # Optional: run once if multiple runs were missed
            max_instances=job_config.get("max_instances", 1), # Optional: prevent concurrent runs
        )
        logger.info(f"Scheduled/Updated job '{job_id}' with trigger: {trigger}")

    except (ValueError, TypeError) as e:
        logger.error(f"Failed to schedule job '{job_id}': Invalid configuration - {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error scheduling job '{job_id}': {e}", exc_info=True)


def remove_job_from_scheduler(job_id: str):
    """
    Removes a job from the APScheduler instance.

    Args:
        job_id: The ID of the job to remove.
    """
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed job '{job_id}' from scheduler.")
    except JobLookupError:
        logger.warning(f"Job '{job_id}' not found in scheduler, cannot remove.")
    except Exception as e:
        logger.error(f"Error removing job '{job_id}' from scheduler: {e}", exc_info=True)

def load_jobs_from_config(config: Dict[str, Any]):
    """
    Loads all jobs defined in the configuration into the scheduler.
    Removes jobs from the scheduler that are no longer in the config.
    """
    configured_jobs = config.get("jobs", {})
    scheduled_job_ids = {job.id for job in scheduler.get_jobs()}
    configured_job_ids = set(configured_jobs.keys())

    # Add/Update jobs from config
    logger.info(f"Loading {len(configured_jobs)} job(s) from configuration...")
    for job_id, job_config in configured_jobs.items():
        add_or_update_job_in_scheduler(job_id, job_config, config)

    # Remove jobs no longer in config
    jobs_to_remove = scheduled_job_ids - configured_job_ids
    if jobs_to_remove:
        logger.info(f"Removing {len(jobs_to_remove)} job(s) not found in current configuration...")
        for job_id in jobs_to_remove:
            remove_job_from_scheduler(job_id)

    logger.info("Job loading complete.")


# --- Web UI Control ---

def start_web_ui_thread(config: Dict[str, Any]):
    """
    Starts the Flask web UI in a separate daemon thread.
    """
    if create_app is None:
         logger.warning("Flask app factory not available. Cannot start web UI.")
         return None # Indicate web UI thread was not started

    config_path = config.get("_config_file_path") # Get original config path
    web_host = config.get("web_server", {}).get("host", "127.0.0.1")
    web_port = config.get("web_server", {}).get("port", 5000)

    def run_flask():
        try:
            # Create app using the factory, passing the config path
            flask_app = create_app(config_path=config_path)
            logger.info(f"Starting Flask web server on http://{web_host}:{web_port}...")
            # Run the Flask development server
            # use_reloader=False is crucial when running inside another process/thread
            # debug=False is recommended for this setup
            flask_app.run(host=web_host, port=web_port, debug=False, use_reloader=False)
            logger.info("Flask web server thread finished.") # Should not happen unless error
        except Exception as e:
            logger.error(f"Flask web server thread failed: {e}", exc_info=True)

    # Start Flask in a daemon thread so it doesn't block scheduler shutdown
    flask_thread = Thread(target=run_flask, daemon=True, name="FlaskWebServerThread")
    flask_thread.start()
    logger.info("Flask web server thread started.")
    return flask_thread


# --- Daemon Control ---

# Store the original config for reload handler
_current_config = {}

def shutdown_scheduler(config: Dict[str, Any], signum=None, frame=None):
    """
    Shuts down the APScheduler instance gracefully and removes the PID file.
    Can be called directly or via signal handler.
    """
    pid_file = config.get("settings", {}).get("pid_file") # Get pid_file from passed config
    if signum:
        logger.info(f"Received signal {signum}. Shutting down scheduler...")
    else:
        logger.info("Initiating scheduler shutdown...")

    logger.info("Attempting graceful shutdown of APScheduler...")
    try:
        # wait=False allows signal handler to exit faster, scheduler shuts down in background
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown initiated.")
        else:
            logger.info("APScheduler was not running.")
    except Exception as e:
        logger.error(f"Error during scheduler shutdown: {e}", exc_info=True)
    finally:
        if pid_file:
            remove_pid(pid_file) # Remove PID file after shutdown attempt
        logger.info("Scheduler shutdown process complete.")
        # Exit the process after handling signal if called by handler
        if signum:
            sys.exit(0)


def reload_config_handler(signum, frame):
    """
    Signal handler for SIGHUP to reload configuration.
    """
    global _current_config
    logger.info(f"Received signal {signum} (SIGHUP). Reloading configuration...")
    config_path = _current_config.get("_config_file_path") # Retrieve original path
    if not config_path:
        logger.error("Cannot reload configuration: Original config file path not stored.")
        return

    try:
        new_config = load_config(config_path)
        # Store the path again in the new config dict for subsequent reloads
        new_config["_config_file_path"] = config_path
        _current_config = new_config # Update the global config reference
        logger.info(f"Successfully reloaded configuration from {config_path}")

        # Reload jobs in the running scheduler
        load_jobs_from_config(_current_config)

    except FileNotFoundError:
        logger.error(f"Failed to reload: Configuration file '{config_path}' not found.")
    except Exception as e:
        logger.error(f"Failed to reload configuration or reschedule jobs: {e}", exc_info=True)


def start_scheduler_process(config: Dict[str, Any]):
    """
    Initializes the database, loads jobs, starts the web UI (if available),
    and starts the scheduler loop. Handles PID file creation/removal and signal handling.
    """
    global _current_config
    _current_config = config # Store config for reload handler
    config_path = config.get("_config_file_path") # Assumes path was added during load_config

    pid_file = config.get("settings", {}).get("pid_file")
    db_path = config.get("settings", {}).get("db_path")

    if not pid_file or not db_path:
         logger.critical("Missing 'pid_file' or 'db_path' in settings. Cannot start.")
         sys.exit(1)

    # Check if already running
    existing_pid = read_pid(pid_file)
    if existing_pid and is_process_running(existing_pid):
        logger.error(f"Scheduler appears to be already running with PID {existing_pid} (PID file: {pid_file}). Aborting.")
        sys.exit(1)
    elif existing_pid:
        logger.warning(f"Found stale PID file '{pid_file}' for PID {existing_pid}. Removing it.")
        remove_pid(pid_file) # Remove stale PID file

    # Write new PID file
    write_pid(pid_file)

    # --- Setup signal handling ---
    # Use a wrapper to pass config to the shutdown handler
    def term_handler(signum, frame):
        # Pass the *currently stored* config to shutdown
        shutdown_scheduler(_current_config, signum, frame)

    signal.signal(signal.SIGTERM, term_handler)
    signal.signal(signal.SIGINT, term_handler) # Handle Ctrl+C gracefully
    signal.signal(signal.SIGHUP, reload_config_handler) # Handle reload signal

    web_thread = None
    try:
        # Initialize Database
        logger.info("Initializing database connection...")
        core_init_db(db_path) # Use the function from core.database

        # Start Web UI in a thread (if available)
        web_thread = start_web_ui_thread(config)

        # Load jobs into scheduler
        logger.info("Loading jobs into scheduler...")
        load_jobs_from_config(config)

        # Start the scheduler's internal loop
        logger.info("Starting APScheduler...")
        scheduler.start()
        logger.info("Scheduler started successfully. Waiting for jobs or signals...")

        # Keep the main thread alive indefinitely until a signal is received
        # signal.pause() is the cleanest way to do this.
        while True:
             signal.pause() # Wait here for signals (TERM, INT, HUP)

    except KeyboardInterrupt:
        # This might be caught here if signal.pause() is interrupted by Ctrl+C
        # before the SIGINT handler fully exits.
        logger.info("KeyboardInterrupt caught in main loop. Initiating shutdown.")
        # The SIGINT handler should have already called shutdown_scheduler
    except Exception as e:
        logger.critical(f"Critical error during scheduler startup or runtime: {e}", exc_info=True)
        # Ensure PID is removed on critical failure before exit
        remove_pid(pid_file) # Attempt cleanup
        sys.exit(1) # Exit with error code
    finally:
        # This block will execute if the loop breaks unexpectedly OR during normal shutdown via sys.exit()
        # Ensure cleanup happens, though signal handler should manage PID removal on TERM/INT.
        logger.info("Scheduler process final cleanup.")
        # Redundant PID removal check in case signal handler failed or loop exited abnormally
        if os.path.exists(pid_file) and read_pid(pid_file) == os.getpid():
             remove_pid(pid_file)
