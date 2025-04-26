# core/scheduler_logic.py

"""
Core logic for the AVScheduler, including job execution, logging,
and interaction with the APScheduler instance.
"""

import os
# import toml # No longer loading config here
import logging
import signal
import sys
import time
from datetime import datetime
from subprocess import Popen, PIPE, TimeoutExpired
from typing import Dict, Any, Optional
# from threading import Thread # No longer starting web thread here

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError

# Assuming database operations are now in core.database
from .database import init_db as core_init_db, log_job_execution
# Assuming condition evaluation is in core.conditions
from .conditions import evaluate_condition
# Import the config loader if needed internally (e.g., for reload handler)
from .config_loader import load_config as core_load_config

# Logging setup (remains the same)
project_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logs_dir = os.path.join(project_root_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
log_file_path = os.path.join(logs_dir, "scheduler.log")
file_handler = logging.FileHandler(log_file_path, mode='a')
file_handler.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler, stream_handler],
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = BackgroundScheduler(daemon=True)

# Store the currently active config for reload handler access
_current_config = {}

# --- PID File Management (remains the same) ---
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
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

# --- Job Execution (remains the same) ---
def execute_job_command(job_id: str, interpreter: str, command: str, env_file: Optional[str] = None, timeout_seconds: Optional[int] = None):
    """
    Executes the job's command in a subprocess and logs results.
    """
    start_time = datetime.now()
    logger.info(f"Starting job '{job_id}' - Command: {interpreter} -c \"{command[:100]}{'...' if len(command) > 100 else ''}\"")
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

    process = None
    stdout_str = None
    stderr_str = None
    exit_code = -1
    try:
        process = Popen(
            [interpreter, "-c", command],
            stdout=PIPE, stderr=PIPE, env=job_env, text=True,
            encoding='utf-8', errors='replace'
        )
        stdout_str, stderr_str = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
        logger.info(f"Job '{job_id}' finished with exit code: {exit_code}")
    except FileNotFoundError:
        logger.error(f"Interpreter '{interpreter}' not found for job '{job_id}'. Check config [interpreters].")
        stderr_str = f"Interpreter not found: {interpreter}"
        exit_code = -2
    except TimeoutExpired:
        logger.warning(f"Job '{job_id}' timed out after {timeout_seconds} seconds. Terminating.")
        if process:
            process.terminate()
            try:
                stdout_str, stderr_str = process.communicate(timeout=5)
            except TimeoutExpired:
                logger.error(f"Job '{job_id}' did not terminate gracefully after timeout. Killing.")
                process.kill()
                stdout_str, stderr_str = process.communicate()
        stderr_str = (stderr_str or "") + "\nJob timed out and was terminated."
        exit_code = -3
    except Exception as e:
        logger.error(f"Error executing job '{job_id}': {e}", exc_info=True)
        stderr_str = (stderr_str or "") + f"\nExecution Error: {e}"
        exit_code = -4
    finally:
        if process and process.poll() is None:
             process.kill()
             logger.warning(f"Force killed job '{job_id}' process due to unexpected state.")

    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()
    logger.info(f"Job '{job_id}' execution time: {execution_time:.3f} seconds")
    if stdout_str: logger.debug(f"Job '{job_id}' STDOUT:\n{stdout_str.strip()}")
    if stderr_str: logger.warning(f"Job '{job_id}' STDERR:\n{stderr_str.strip()}")
    return exit_code, execution_time, stdout_str, stderr_str

def run_job_wrapper(job_id: str, config: Dict[str, Any]):
    """
    Wrapper function called by APScheduler.
    Loads job details, checks conditions, executes the job, and logs to DB.
    Uses the config dictionary passed during scheduling.
    """
    logger.info(f"Scheduler triggered for job '{job_id}'")
    job_config = config.get("jobs", {}).get(job_id)
    if not job_config:
        logger.error(f"Job configuration for '{job_id}' not found in passed config. Skipping.")
        return

    interpreter_type = job_config.get("type")
    interpreter_path = config.get("interpreters", {}).get(interpreter_type)
    command = job_config.get("command")
    condition_str = job_config.get("condition")
    env_file = job_config.get("env_file")
    db_path = config.get("settings", {}).get("db_path")
    timeout = job_config.get("timeout_seconds")

    if not interpreter_path:
        logger.error(f"Interpreter type '{interpreter_type}' for job '{job_id}' not defined in [interpreters]. Skipping.")
        if db_path: log_job_execution(job_id, -5, 0, stderr="Interpreter type not configured")
        return
    if not command:
        logger.error(f"Job '{job_id}' has no command defined. Skipping.")
        if db_path: log_job_execution(job_id, -6, 0, stderr="Job command not defined")
        return
    if not db_path:
         logger.error(f"Database path not configured in [settings]. Cannot log or check conditions for job '{job_id}'. Skipping.")
         return

    # Condition Check
    if condition_str:
        logger.debug(f"Checking condition for job '{job_id}': {condition_str}")
        try:
            condition_met = evaluate_condition(condition_str, db_path, job_id)
            if not condition_met:
                logger.info(f"Skipping job '{job_id}' because its condition is not met: {condition_str}")
                return
            else:
                 logger.debug(f"Condition met for job '{job_id}'.")
        except Exception as e:
            logger.error(f"Error evaluating condition for job '{job_id}': {e}. Skipping job.", exc_info=True)
            log_job_execution(job_id, -7, 0, stderr=f"Condition evaluation error: {e}")
            return

    # Execute Job
    exit_code, exec_time, stdout, stderr = execute_job_command(
        job_id, interpreter_path, command, env_file, timeout
    )

    # Log to Database
    log_job_execution(job_id, exit_code, exec_time, stdout, stderr)


# --- Scheduler Management (remains mostly the same) ---
def add_or_update_job_in_scheduler(job_id: str, job_config: Dict[str, Any], config: Dict[str, Any]):
    """Adds/updates job in APScheduler instance."""
    schedule_type = job_config.get("schedule_type", "cron")
    trigger = None
    try:
        if schedule_type == "cron":
            cron_schedule = job_config.get("schedule")
            if not cron_schedule: raise ValueError("Missing 'schedule' for cron job.")
            trigger = CronTrigger.from_crontab(cron_schedule, timezone='UTC')
        elif schedule_type == "interval":
            interval_seconds = job_config.get("interval_seconds")
            if interval_seconds is None: raise ValueError("Missing 'interval_seconds' for interval job.")
            trigger = IntervalTrigger(seconds=int(interval_seconds), timezone='UTC')
        elif schedule_type == "date":
            run_date_str = job_config.get("run_date")
            if not run_date_str: raise ValueError("Missing 'run_date' for date job.")
            run_date = datetime.fromisoformat(run_date_str)
            trigger = DateTrigger(run_date=run_date, timezone='UTC')
        else:
            raise ValueError(f"Unsupported schedule_type: {schedule_type}")

        scheduler.add_job(
            func=run_job_wrapper, args=[job_id, config], trigger=trigger, id=job_id,
            name=job_config.get("name", job_id), replace_existing=True,
            misfire_grace_time=job_config.get("misfire_grace_time", 60),
            coalesce=job_config.get("coalesce", True),
            max_instances=job_config.get("max_instances", 1),
        )
        logger.info(f"Scheduled/Updated job '{job_id}' with trigger: {trigger}")
    except (ValueError, TypeError) as e:
        logger.error(f"Failed to schedule job '{job_id}': Invalid configuration - {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error scheduling job '{job_id}': {e}", exc_info=True)

def remove_job_from_scheduler(job_id: str):
    """Removes job from APScheduler instance."""
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed job '{job_id}' from scheduler.")
    except JobLookupError:
        logger.warning(f"Job '{job_id}' not found in scheduler, cannot remove.")
    except Exception as e:
        logger.error(f"Error removing job '{job_id}' from scheduler: {e}", exc_info=True)

def load_jobs_from_config(config: Dict[str, Any]):
    """Loads/reloads jobs from config into the scheduler."""
    global _current_config
    _current_config = config # Update internal reference for wrappers/handlers
    configured_jobs = config.get("jobs", {})
    scheduled_job_ids = {job.id for job in scheduler.get_jobs()}
    configured_job_ids = set(configured_jobs.keys())

    logger.info(f"Loading {len(configured_jobs)} job(s) from configuration...")
    for job_id, job_config in configured_jobs.items():
        # Pass the *current* config to the scheduler
        add_or_update_job_in_scheduler(job_id, job_config, _current_config)

    jobs_to_remove = scheduled_job_ids - configured_job_ids
    if jobs_to_remove:
        logger.info(f"Removing {len(jobs_to_remove)} job(s) not found in current configuration...")
        for job_id in jobs_to_remove:
            remove_job_from_scheduler(job_id)
    logger.info("Job loading complete.")


# --- Daemon Control Logic (No Web Start) ---

def shutdown_scheduler(config: Dict[str, Any], signum=None, frame=None):
    """Shuts down APScheduler and removes PID file."""
    pid_file = config.get("settings", {}).get("pid_file")
    if signum: logger.info(f"Received signal {signum}. Shutting down scheduler...")
    else: logger.info("Initiating scheduler shutdown...")

    logger.info("Attempting graceful shutdown of APScheduler...")
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown initiated.")
        else:
            logger.info("APScheduler was not running.")
    except Exception as e:
        logger.error(f"Error during scheduler shutdown: {e}", exc_info=True)
    finally:
        if pid_file: remove_pid(pid_file)
        logger.info("Scheduler shutdown process complete.")
        if signum: sys.exit(0)

def reload_config_handler(signum, frame):
    """Signal handler for SIGHUP to reload configuration."""
    global _current_config
    logger.info(f"Received signal {signum} (SIGHUP). Reloading configuration...")
    config_path = _current_config.get("_config_file_path")
    if not config_path:
        logger.error("Cannot reload configuration: Original config file path not stored.")
        return
    try:
        new_config = core_load_config(config_path) # Use the extracted loader
        # new_config["_config_file_path"] = config_path # Loader adds this now
        # _current_config = new_config # load_jobs_from_config will update _current_config
        logger.info(f"Successfully reloaded configuration from {config_path}")
        load_jobs_from_config(new_config) # Pass newly loaded config
    except FileNotFoundError:
        logger.error(f"Failed to reload: Configuration file '{config_path}' not found.")
    except Exception as e:
        logger.error(f"Failed to reload configuration or reschedule jobs: {e}", exc_info=True)


def start_scheduler_process(config: Dict[str, Any]):
    """
    Initializes DB, loads jobs, starts scheduler loop. Handles PID and signals.
    DOES NOT START THE WEB UI.
    """
    global _current_config
    _current_config = config # Store initial config

    pid_file = config.get("settings", {}).get("pid_file")
    db_path = config.get("settings", {}).get("db_path")

    if not pid_file or not db_path:
         logger.critical("Missing 'pid_file' or 'db_path' in settings. Cannot start.")
         sys.exit(1)

    # PID check (remains the same)
    existing_pid = read_pid(pid_file)
    if existing_pid and is_process_running(existing_pid):
        logger.error(f"Scheduler appears to be already running with PID {existing_pid}. Aborting.")
        sys.exit(1)
    elif existing_pid:
        logger.warning(f"Found stale PID file '{pid_file}'. Removing it.")
        remove_pid(pid_file)

    write_pid(pid_file)

    # Signal handling setup
    def term_handler(signum, frame):
        shutdown_scheduler(_current_config, signum, frame) # Use stored config

    signal.signal(signal.SIGTERM, term_handler)
    signal.signal(signal.SIGINT, term_handler)
    signal.signal(signal.SIGHUP, reload_config_handler)

    try:
        # DB Init is now done *before* calling this function by the entry point
        # logger.info("Initializing database connection...")
        # core_init_db(db_path) # Moved to entry point

        # Load initial jobs
        logger.info("Loading initial jobs into scheduler...")
        load_jobs_from_config(config) # Use the initially passed config

        # Start the scheduler's internal loop
        logger.info("Starting APScheduler...")
        scheduler.start()
        logger.info("Scheduler started successfully. Waiting for jobs or signals...")

        # Keep the main thread alive
        while True:
             signal.pause()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught in main loop. Initiating shutdown.")
    except Exception as e:
        logger.critical(f"Critical error during scheduler startup or runtime: {e}", exc_info=True)
        remove_pid(pid_file)
        sys.exit(1)
    finally:
        logger.info("Scheduler process final cleanup.")
        if os.path.exists(pid_file) and read_pid(pid_file) == os.getpid():
             remove_pid(pid_file)
