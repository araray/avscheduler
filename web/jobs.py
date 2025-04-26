# web/jobs.py

"""
Flask Blueprint for managing scheduler jobs (Add, Edit, Delete) via the web UI.
Handles interaction with the configuration file and potentially the scheduler.
"""

import os
import toml
import logging
import uuid # Import for generating IDs
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, current_app, g
)
from werkzeug.exceptions import NotFound
from datetime import datetime # Import datetime for parsing

# Import the form defined for jobs
from .forms import JobForm
# Import core components needed
from core.config_loader import load_config # To load/save config
from core.scheduler_logic import add_or_update_job_in_scheduler, remove_job_from_scheduler # For Phase 4 integration

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
    """Saves TOML config or flashes an error and returns False on failure."""
    try:
        # Ensure 'jobs' section exists before saving
        config_data.setdefault("jobs", {})
        with open(config_path, "w") as f:
            toml.dump(config_data, f)
        logger.info(f"Configuration saved successfully to: {config_path}")
        # Trigger reload in running scheduler (Phase 4 - Placeholder)
        _trigger_scheduler_reload()
        return True
    except IOError as e:
        logger.error(f"Error writing configuration file '{config_path}': {e}", exc_info=True)
        flash(f"Error: Failed to write configuration file '{config_path}'.", "error")
    except Exception as e:
        logger.error(f"Unexpected error saving configuration: {e}", exc_info=True)
        flash("An unexpected error occurred while saving the configuration.", "error")
    return False

def _trigger_scheduler_reload():
    """
    Placeholder function to signal the running scheduler to reload config.
    Actual implementation depends on Phase 4 (e.g., sending SIGHUP, IPC).
    """
    # In a real implementation (Phase 4):
    # - Get PID from config['settings']['pid_file']
    # - Send signal.SIGHUP to the PID
    # - Or use another IPC mechanism
    logger.info("Placeholder: Triggering scheduler config reload (needs Phase 4 implementation).")
    flash("Configuration saved. Please manually reload or restart the scheduler daemon for changes to take full effect.", "warning")

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
    config_path = current_app.config.get('SCHEDULER_CONFIG', {}).get('_config_file_path')
    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    config = _load_config_or_flash(config_path)
    if config is None:
        return redirect(url_for('routes.index')) # Redirect if config loading failed

    form = JobForm()
    # Populate choices for job_type dynamically from config
    interpreter_choices = [(key, key) for key in config.get("interpreters", {}).keys()]
    form.job_type.choices = interpreter_choices

    if form.validate_on_submit():
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
            # Don't redirect, let user fix the ID
            return render_template("add_edit_job.html", form=form, mode='add', job_id=None)

        # Create new job entry
        new_job_data = {
            "type": form.job_type.data, # Use form field name
            "schedule_type": form.schedule_type.data,
            "command": form.command.data,
            # Add optional fields if they have data
            **({ "name": form.name.data } if form.name.data else {}),
            **({ "condition": form.condition.data } if form.condition.data else {}),
            **({ "env_file": form.env_file.data } if form.env_file.data else {}),
            **({ "timeout_seconds": form.timeout_seconds.data } if form.timeout_seconds.data is not None else {}),
            **({ "misfire_grace_time": form.misfire_grace_time.data } if form.misfire_grace_time.data is not None else {}),
            **({ "coalesce": form.coalesce.data }), # Boolean, always include
            **({ "max_instances": form.max_instances.data } if form.max_instances.data is not None else {}),
        }

        # Add schedule-specific fields
        if form.schedule_type.data == 'cron':
            new_job_data["schedule"] = form.schedule.data
        elif form.schedule_type.data == 'interval':
            new_job_data["interval_seconds"] = form.interval_seconds.data
        elif form.schedule_type.data == 'date':
            # Format datetime object back to string for TOML
            new_job_data["run_date"] = form.run_date.data.strftime('%Y-%m-%d %H:%M:%S') if form.run_date.data else None

        jobs[job_id] = new_job_data

        # Save updated config back to file
        if _save_config_or_flash(config_path, config):
            if generated_id:
                flash(f"Job added successfully with generated ID '{job_id}'!", "success")
            else:
                flash(f"Job '{job_id}' added successfully!", "success")
            return redirect(url_for('routes.index'))
        else:
            # Saving failed, stay on page, error flashed by helper
             return render_template("add_edit_job.html", form=form, mode='add', job_id=None)

    elif request.method == "POST":
         # Form validation failed
         flash("Please correct the errors below.", "warning")

    # GET request or validation failed on POST
    return render_template("add_edit_job.html", form=form, mode='add', job_id=None)


@bp.route("/edit/<job_id>", methods=["GET", "POST"])
def edit_job(job_id):
    """Route to display and handle editing an existing job."""
    config_path = current_app.config.get('SCHEDULER_CONFIG', {}).get('_config_file_path')
    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    config = _load_config_or_flash(config_path)
    if config is None:
        return redirect(url_for('routes.index'))

    jobs = config.get("jobs", {})
    job_data = jobs.get(job_id)

    if not job_data:
        logger.warning(f"Edit attempt failed: Job ID '{job_id}' not found in config.")
        flash(f"Job ID '{job_id}' not found.", "error")
        raise NotFound() # Return 404

    # --- Pre-population Logic ---
    # Create the form instance first
    form = JobForm()

    # Populate choices for job_type dynamically before setting data
    interpreter_choices = [(key, key) for key in config.get("interpreters", {}).keys()]
    form.job_type.choices = interpreter_choices

    # On GET request, pre-populate form fields from job_data
    if request.method == 'GET':
        form.job_id.data = job_id # Set the ID from the URL
        form.name.data = job_data.get('name')
        form.job_type.data = job_data.get('type') # Map 'type' from config
        form.command.data = job_data.get('command')
        form.schedule_type.data = job_data.get('schedule_type')
        form.schedule.data = job_data.get('schedule')
        form.interval_seconds.data = job_data.get('interval_seconds')
        # Parse run_date string into datetime object for the form field
        run_date_str = job_data.get('run_date')
        if run_date_str and isinstance(run_date_str, str):
            try:
                form.run_date.data = datetime.strptime(run_date_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                logger.warning(f"Could not parse run_date '{run_date_str}' for job '{job_id}'.")
                form.run_date.data = None # Clear if invalid format
        else:
             form.run_date.data = None # Set to None if not present or not string

        form.condition.data = job_data.get('condition')
        form.env_file.data = job_data.get('env_file')
        form.timeout_seconds.data = job_data.get('timeout_seconds')
        form.misfire_grace_time.data = job_data.get('misfire_grace_time')
        # WTForms handles boolean default correctly, but explicit set is safer
        form.coalesce.data = job_data.get('coalesce', True)
        form.max_instances.data = job_data.get('max_instances', 1)

    # Set job_id field as read-only for editing (applies to both GET and POST rendering)
    form.job_id.render_kw = {'readonly': True}
    # --- End Pre-population Logic ---


    if form.validate_on_submit():
        # Update job data in the config dictionary
        # Use job_id from URL parameter, not form data (as it's readonly)
        updated_job_data = {
            "type": form.job_type.data,
            "schedule_type": form.schedule_type.data,
            "command": form.command.data,
            # Add optional fields if they have data
            **({ "name": form.name.data } if form.name.data else {}),
            **({ "condition": form.condition.data } if form.condition.data else {}),
            **({ "env_file": form.env_file.data } if form.env_file.data else {}),
            **({ "timeout_seconds": form.timeout_seconds.data } if form.timeout_seconds.data is not None else {}),
            **({ "misfire_grace_time": form.misfire_grace_time.data } if form.misfire_grace_time.data is not None else {}),
            **({ "coalesce": form.coalesce.data }), # Boolean, always include
            **({ "max_instances": form.max_instances.data } if form.max_instances.data is not None else {}),
        }

        # Add/update schedule-specific fields, remove old ones if type changed
        updated_job_data.pop("schedule", None)
        updated_job_data.pop("interval_seconds", None)
        updated_job_data.pop("run_date", None)

        if form.schedule_type.data == 'cron':
            updated_job_data["schedule"] = form.schedule.data
        elif form.schedule_type.data == 'interval':
            updated_job_data["interval_seconds"] = form.interval_seconds.data
        elif form.schedule_type.data == 'date':
            updated_job_data["run_date"] = form.run_date.data.strftime('%Y-%m-%d %H:%M:%S') if form.run_date.data else None

        # Replace the old job data with the updated data using the job_id from URL
        jobs[job_id] = updated_job_data

        # Save updated config back to file
        if _save_config_or_flash(config_path, config):
            flash(f"Job '{job_id}' updated successfully!", "success")
            return redirect(url_for('routes.job_details', job_id=job_id))
        else:
             # Saving failed, stay on page, error flashed by helper
             # Form already contains submitted data due to validate_on_submit
             # Need to ensure choices are still populated and ID is readonly
             form.job_type.choices = interpreter_choices
             form.job_id.render_kw = {'readonly': True}
             form.job_id.data = job_id # Ensure job_id data is set
             return render_template("add_edit_job.html", form=form, mode='edit', job_id=job_id)

    elif request.method == "POST":
        # Form validation failed on POST
        flash("Please correct the errors below.", "warning")
        # Form instance already contains submitted data and validation errors
        # Need to re-populate dynamic choices and set readonly attribute again
        form.job_type.choices = interpreter_choices
        form.job_id.render_kw = {'readonly': True}
        form.job_id.data = job_id # Ensure job_id data is set even on failed POST

    # GET request or validation failed on POST
    # Form instance (either from GET pre-population or failed POST) is passed
    return render_template("add_edit_job.html", form=form, mode='edit', job_id=job_id)


@bp.route("/delete/<job_id>", methods=["POST"]) # Use POST for deletion
def delete_job(job_id):
    """Route to handle deleting a job."""
    config_path = current_app.config.get('SCHEDULER_CONFIG', {}).get('_config_file_path')
    if not config_path:
        flash("Configuration file path not found in application settings.", "error")
        return redirect(url_for('routes.index'))

    config = _load_config_or_flash(config_path)
    if config is None:
        return redirect(url_for('routes.index'))

    jobs = config.get("jobs", {})

    if job_id not in jobs:
        logger.warning(f"Delete attempt failed: Job ID '{job_id}' not found in config.")
        flash(f"Job ID '{job_id}' not found.", "error")
        raise NotFound() # Return 404

    # Remove job from config dictionary
    del jobs[job_id]

    # Save updated config back to file
    if _save_config_or_flash(config_path, config):
        # Also remove from running scheduler (Phase 4 - Placeholder)
        # scheduler = g.get('scheduler')
        # if scheduler:
        #     remove_job_from_scheduler(job_id) # Use core function
        flash(f"Job '{job_id}' deleted successfully!", "success")
    else:
        # Saving failed, error flashed by helper
        # Re-add job to config temporarily if save failed? No, maybe better to leave it deleted
        # but warn the user the file wasn't saved.
        flash(f"Job '{job_id}' was removed from memory, but the configuration file could not be saved.", "error")


    return redirect(url_for('routes.index'))
