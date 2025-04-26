# web/jobs.py

"""
Flask Blueprint for managing scheduler jobs (Add, Edit, Delete) via the web UI.
Handles interaction with the configuration file and triggers daemon reload.
"""

import os
import toml
import logging
import uuid # Import for generating IDs
import signal # Import signal for SIGHUP
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, current_app, g
)
from werkzeug.exceptions import NotFound
from datetime import datetime # Import datetime for parsing

# Import the form defined for jobs
from .forms import JobForm
# Import core components needed
from core.config_loader import load_config # To load/save config
# Import helpers for signaling daemon
from core.scheduler_logic import read_pid, is_process_running

# Create Blueprint
bp = Blueprint('jobs', __name__, url_prefix='/jobs')

logger = logging.getLogger(__name__)

# --- Helper Functions ---

def _load_config_or_flash(config_path):
    """Loads TOML config or flashes an error and returns None."""
    try:
        return load_config(config_path)
    except FileNotFoundError:
        logger.error(f"Configuration file not found at: {config_path}")
        flash(f"Error: Configuration file not found at '{config_path}'.", "error")
    except toml.TomlDecodeError as e:
        logger.error(f"Error decoding TOML configuration file '{config_path}': {e}")
        flash(f"Error: Configuration file '{config_path}' is not valid TOML.", "error")
    except ValueError as e:
        logger.error(f"Configuration validation error: {e}")
        flash(f"Error: Configuration validation failed: {e}", "error")
    except Exception as e:
        logger.error(f"Unexpected error loading configuration: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the configuration.", "error")
    return None

def _save_config_or_flash(config_path, config_data):
    """Saves TOML config, triggers daemon reload, updates app config, or flashes error."""
    try:
        # Ensure 'jobs' section exists before saving
        config_data.setdefault("jobs", {})
        with open(config_path, "w") as f:
            toml.dump(config_data, f)
        logger.info(f"Configuration saved successfully to: {config_path}")

        # --- Update Web UI's in-memory config ---
        # This makes the change effective for subsequent requests in the same worker
        current_app.config['SCHEDULER_CONFIG'] = config_data
        logger.info("Web UI in-memory configuration updated.")
        # --- End Web UI Update ---

        # --- Trigger reload in running scheduler daemon ---
        reload_status = _trigger_scheduler_reload(config_data)
        # --- End Daemon Trigger ---

        # Flash appropriate message based on reload status
        if reload_status == "success":
            flash("Configuration saved and reload signal sent to daemon.", "info")
        elif reload_status == "not_running":
            flash("Configuration saved, but daemon does not appear to be running. Please start/restart it manually.", "warning")
        else: # "error" or other issues
            flash("Configuration saved, but failed to send reload signal to daemon. Check logs and restart manually if needed.", "error")

        return True # Indicate config file was saved

    except IOError as e:
        logger.error(f"Error writing configuration file '{config_path}': {e}", exc_info=True)
        flash(f"Error: Failed to write configuration file '{config_path}'.", "error")
    except Exception as e:
        logger.error(f"Unexpected error saving configuration: {e}", exc_info=True)
        flash("An unexpected error occurred while saving the configuration.", "error")
    return False

def _trigger_scheduler_reload(config_data) -> str:
    """
    Sends SIGHUP to the running scheduler daemon process.

    Args:
        config_data: The configuration dictionary (to find pid_file).

    Returns:
        A status string: "success", "not_running", or "error".
    """
    pid_file = config_data.get("settings", {}).get("pid_file")
    if not pid_file:
        logger.error("Cannot trigger daemon reload: 'pid_file' not found in configuration.")
        return "error"

    pid = read_pid(pid_file)
    if not pid:
        logger.warning(f"Cannot trigger daemon reload: PID file '{pid_file}' not found or empty.")
        return "not_running" # Daemon likely not running

    if not is_process_running(pid):
        logger.warning(f"Cannot trigger daemon reload: Process with PID {pid} (from '{pid_file}') not found.")
        # Clean up stale PID file? Maybe not here, let status/stop handle it.
        return "not_running"

    # Send the SIGHUP signal
    logger.info(f"Sending SIGHUP signal to scheduler process PID {pid} to trigger configuration reload...")
    try:
        os.kill(pid, signal.SIGHUP)
        logger.info(f"SIGHUP signal sent successfully to PID {pid}.")
        return "success"
    except ProcessLookupError:
        logger.error(f"Error sending SIGHUP: Process with PID {pid} disappeared unexpectedly.", exc_info=True)
        return "not_running" # Process died
    except PermissionError:
        logger.error(f"Error sending SIGHUP: Permission denied for PID {pid}. Try running web server/daemon as same user?", exc_info=True)
        return "error"
    except Exception as e:
        logger.error(f"An unexpected error occurred while sending SIGHUP signal to PID {pid}: {e}", exc_info=True)
        return "error"


def _generate_unique_job_id(existing_ids: set) -> str:
    """Generates a unique 8-character hex job ID."""
    while True:
        new_id = uuid.uuid4().hex[:8] # Generate 8-char hex ID
        if new_id not in existing_ids:
            return new_id
        logger.debug(f"Generated job ID {new_id} collided, regenerating.")


# --- Routes ---

@bp.route("/add", methods=["GET", "POST"])
def add_job():
    """Route to display and handle adding a new job."""
    # Use the config stored in the app context for consistency within the request
    config = g.get('config', {})
    config_path = config.get('_config_file_path') # Get path from loaded config

    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    # Load fresh config from disk *only* for validation/choices if needed,
    # but operate on the 'g.config' for modifications within the request lifecycle.
    # Using g.config avoids potential race conditions if multiple requests happen.
    # However, saving writes the modified g.config back to disk.

    form = JobForm()
    # Populate choices for job_type dynamically from config
    interpreter_choices = [(key, key) for key in config.get("interpreters", {}).keys()]
    form.job_type.choices = interpreter_choices

    # *** FIX: Initialize render_kw for job_id in add mode ***
    form.job_id.render_kw = {} # Ensure it's a dict, even if empty

    if form.validate_on_submit():
        # Operate on a copy of the config from 'g' or load fresh?
        # Let's modify the 'config' object directly (which is g.config)
        # and then save it.
        jobs = config.setdefault("jobs", {})
        job_id = form.job_id.data # Get user input (might be empty)
        generated_id = False

        # --- Auto-generate ID if not provided ---
        if not job_id:
            job_id = _generate_unique_job_id(set(jobs.keys()))
            generated_id = True
            logger.info(f"No Job ID provided, generated unique ID: {job_id}")
        # --- End Auto-generation ---

        elif job_id in jobs: # Check for collision only if user provided ID
            flash(f"Job ID '{job_id}' already exists. Please choose a unique ID or leave blank to auto-generate.", "error")
            return render_template("add_edit_job.html", form=form, mode='add', job_id=None)

        # Create new job entry
        new_job_data = {
            "type": form.job_type.data,
            "schedule_type": form.schedule_type.data,
            "command": form.command.data,
            **({ "name": form.name.data } if form.name.data else {}),
            **({ "condition": form.condition.data } if form.condition.data else {}),
            **({ "env_file": form.env_file.data } if form.env_file.data else {}),
            **({ "timeout_seconds": form.timeout_seconds.data } if form.timeout_seconds.data is not None else {}),
            **({ "misfire_grace_time": form.misfire_grace_time.data } if form.misfire_grace_time.data is not None else {}),
            **({ "coalesce": form.coalesce.data }),
            **({ "max_instances": form.max_instances.data } if form.max_instances.data is not None else {}),
        }

        # Add schedule-specific fields
        if form.schedule_type.data == 'cron':
            new_job_data["schedule"] = form.schedule.data
        elif form.schedule_type.data == 'interval':
            new_job_data["interval_seconds"] = form.interval_seconds.data
        elif form.schedule_type.data == 'date':
            new_job_data["run_date"] = form.run_date.data.strftime('%Y-%m-%d %H:%M:%S') if form.run_date.data else None

        jobs[job_id] = new_job_data

        # Save the modified 'config' object back to file and trigger reload
        if _save_config_or_flash(config_path, config):
            # Flash message handled by _save_config_or_flash
            return redirect(url_for('routes.index'))
        else:
            # Saving failed, remove the added job from the in-memory config
            # to prevent inconsistent state before re-rendering
            jobs.pop(job_id, None)
            return render_template("add_edit_job.html", form=form, mode='add', job_id=None)

    elif request.method == "POST":
         flash("Please correct the errors below.", "warning")
         # Ensure render_kw is still set even on failed POST for re-render
         form.job_id.render_kw = {}

    # GET request or validation failed on POST
    return render_template("add_edit_job.html", form=form, mode='add', job_id=None)


@bp.route("/edit/<job_id>", methods=["GET", "POST"])
def edit_job(job_id):
    """Route to display and handle editing an existing job."""
    config = g.get('config', {})
    config_path = config.get('_config_file_path')

    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    # Load a fresh copy for editing to avoid modifying 'g.config' before saving
    config_to_edit = _load_config_or_flash(config_path)
    if config_to_edit is None:
         return redirect(url_for('routes.index')) # Redirect if config loading failed

    jobs = config_to_edit.get("jobs", {})
    job_data = jobs.get(job_id)

    if not job_data:
        logger.warning(f"Edit attempt failed: Job ID '{job_id}' not found in config.")
        flash(f"Job ID '{job_id}' not found.", "error")
        raise NotFound() # Return 404

    # --- Pre-population Logic ---
    form = JobForm()
    interpreter_choices = [(key, key) for key in config_to_edit.get("interpreters", {}).keys()]
    form.job_type.choices = interpreter_choices

    if request.method == 'GET':
        form.job_id.data = job_id
        form.name.data = job_data.get('name')
        form.job_type.data = job_data.get('type')
        form.command.data = job_data.get('command')
        form.schedule_type.data = job_data.get('schedule_type')
        form.schedule.data = job_data.get('schedule')
        form.interval_seconds.data = job_data.get('interval_seconds')
        run_date_str = job_data.get('run_date')
        if run_date_str and isinstance(run_date_str, str):
            try:
                form.run_date.data = datetime.strptime(run_date_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                logger.warning(f"Could not parse run_date '{run_date_str}' for job '{job_id}'.")
                form.run_date.data = None
        else:
             form.run_date.data = None
        form.condition.data = job_data.get('condition')
        form.env_file.data = job_data.get('env_file')
        form.timeout_seconds.data = job_data.get('timeout_seconds')
        form.misfire_grace_time.data = job_data.get('misfire_grace_time')
        form.coalesce.data = job_data.get('coalesce', True)
        form.max_instances.data = job_data.get('max_instances', 1)

    # Set job_id field as read-only for editing (applies to both GET and POST rendering)
    form.job_id.render_kw = {'readonly': True}
    # --- End Pre-population Logic ---


    if form.validate_on_submit():
        # Update job data in the loaded config dictionary (config_to_edit)
        updated_job_data = {
            "type": form.job_type.data,
            "schedule_type": form.schedule_type.data,
            "command": form.command.data,
            **({ "name": form.name.data } if form.name.data else {}),
            **({ "condition": form.condition.data } if form.condition.data else {}),
            **({ "env_file": form.env_file.data } if form.env_file.data else {}),
            **({ "timeout_seconds": form.timeout_seconds.data } if form.timeout_seconds.data is not None else {}),
            **({ "misfire_grace_time": form.misfire_grace_time.data } if form.misfire_grace_time.data is not None else {}),
            **({ "coalesce": form.coalesce.data }),
            **({ "max_instances": form.max_instances.data } if form.max_instances.data is not None else {}),
        }

        updated_job_data.pop("schedule", None)
        updated_job_data.pop("interval_seconds", None)
        updated_job_data.pop("run_date", None)

        if form.schedule_type.data == 'cron':
            updated_job_data["schedule"] = form.schedule.data
        elif form.schedule_type.data == 'interval':
            updated_job_data["interval_seconds"] = form.interval_seconds.data
        elif form.schedule_type.data == 'date':
            updated_job_data["run_date"] = form.run_date.data.strftime('%Y-%m-%d %H:%M:%S') if form.run_date.data else None

        # Replace the old job data in the config_to_edit dictionary
        jobs[job_id] = updated_job_data

        # Save the modified config_to_edit back to file and trigger reload
        if _save_config_or_flash(config_path, config_to_edit):
             # Flash message handled by _save_config_or_flash
            return redirect(url_for('routes.job_details', job_id=job_id))
        else:
             # Saving failed, stay on page
             form.job_type.choices = interpreter_choices
             form.job_id.render_kw = {'readonly': True}
             form.job_id.data = job_id
             return render_template("add_edit_job.html", form=form, mode='edit', job_id=job_id)

    elif request.method == "POST":
        flash("Please correct the errors below.", "warning")
        form.job_type.choices = interpreter_choices
        # Ensure render_kw is set correctly even on failed POST for re-render
        form.job_id.render_kw = {'readonly': True}
        form.job_id.data = job_id

    # GET request or validation failed on POST
    return render_template("add_edit_job.html", form=form, mode='edit', job_id=job_id)


@bp.route("/delete/<job_id>", methods=["POST"]) # Use POST for deletion
def delete_job(job_id):
    """Route to handle deleting a job."""
    config = g.get('config', {})
    config_path = config.get('_config_file_path')

    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    # Load fresh config to modify
    config_to_edit = _load_config_or_flash(config_path)
    if config_to_edit is None:
        return redirect(url_for('routes.index'))

    jobs = config_to_edit.get("jobs", {})

    if job_id not in jobs:
        logger.warning(f"Delete attempt failed: Job ID '{job_id}' not found in config.")
        flash(f"Job ID '{job_id}' not found.", "error")
        raise NotFound() # Return 404

    # Store original job data in case save fails and we need to revert web UI config
    original_job_data = jobs.pop(job_id) # Remove job from config dictionary

    # Save updated config back to file
    if _save_config_or_flash(config_path, config_to_edit):
        # Flash message handled by _save_config_or_flash
        pass # Success message handled by _save_config_or_flash
    else:
        # Saving failed, error flashed by helper
        # Since saving the file failed, the daemon wasn't signaled and the web UI's
        # in-memory config wasn't updated by _save_config_or_flash.
        # We should probably revert the change in the currently loaded config_to_edit
        # although it won't be used further in this request.
        jobs[job_id] = original_job_data # Revert deletion in local copy
        flash(f"Job '{job_id}' could not be deleted because the configuration file could not be saved.", "error")

    return redirect(url_for('routes.index'))
