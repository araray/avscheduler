# web/routes.py

"""
Defines the main web routes for viewing job status and logs using Flask Blueprints.
"""

import logging
from flask import Blueprint, render_template, redirect, url_for, g, current_app, flash
from sqlalchemy.exc import SQLAlchemyError

# Import necessary components from core
# Assuming database models and session management are handled via g.db_session
from core.database import JobExecutionLog, delete_job_logs as core_delete_job_logs, get_distinct_job_ids, get_latest_job_log, get_job_logs

# Create a Blueprint
bp = Blueprint('routes', __name__)

logger = logging.getLogger(__name__)

@bp.route("/")
def index():
    """
    Dashboard route. Displays a list of jobs and their latest status.
    """
    jobs_summary = []
    config = g.get('config', {}) # Get config loaded in app factory
    scheduler = g.get('scheduler') # Get scheduler instance from app context
    session = g.get('db_session')

    if session is None:
        flash("Database connection not available.", "error")
        return render_template("index.html", jobs=jobs_summary)
    if scheduler is None:
         # Don't flash error here, maybe scheduler isn't running but we can still show logs
         logger.warning("Scheduler instance not available in web context. Next run times will be unavailable.")


    try:
        # Get distinct job IDs from logs OR from config (more reliable if job never ran)
        # Let's use config as the primary source of job IDs
        job_ids_from_config = list(config.get('jobs', {}).keys())
        logger.debug(f"Found job IDs in config: {job_ids_from_config}")

        # distinct_job_ids = get_distinct_job_ids() # Uses DB session via g

        for job_id in job_ids_from_config:
            job_info = config.get('jobs', {}).get(job_id, {})
            latest_log = get_latest_job_log(job_id) # Uses DB session via g

            # Get next execution time from the scheduler instance
            next_execution = "N/A"
            if scheduler:
                try:
                    apscheduler_job = scheduler.get_job(job_id)
                    if apscheduler_job and apscheduler_job.next_run_time:
                        # Format datetime nicely
                        next_execution = apscheduler_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')
                    elif apscheduler_job:
                        next_execution = "Scheduled (no next run)" # e.g., paused or finished
                    else:
                        next_execution = "Not Scheduled"
                except Exception as e:
                    logger.error(f"Error getting next run time for job '{job_id}' from scheduler: {e}")
                    next_execution = "Error"
            else:
                next_execution = "Scheduler Unavailable"


            jobs_summary.append({
                "id": job_id,
                "last_execution": latest_log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_log else "N/A",
                "last_exit_code": latest_log.exit_code if latest_log else "N/A",
                "last_execution_time": f"{latest_log.execution_time:.3f}" if latest_log else "N/A",
                "next_execution": next_execution,
                "condition": job_info.get("condition", "N/A"),
                "type": job_info.get("type", "N/A"),
                "schedule_info": get_schedule_display(job_info), # Helper for schedule display
            })

    except SQLAlchemyError as e:
        logger.error(f"Database error on index page: {e}", exc_info=True)
        flash("Error retrieving job status from database.", "error")
    except Exception as e:
        logger.error(f"Unexpected error on index page: {e}", exc_info=True)
        flash("An unexpected error occurred.", "error")

    # Sort jobs by ID for consistent display
    jobs_summary.sort(key=lambda j: j['id'])

    return render_template("index.html", jobs=jobs_summary)


@bp.route("/job/<job_id>")
def job_details(job_id):
    """
    Displays the execution log history for a specific job.
    """
    logs = []
    job_config = g.get('config', {}).get('jobs', {}).get(job_id, {})
    session = g.get('db_session')

    if session is None:
        flash("Database connection not available.", "error")
        return render_template("job_details.html", job_id=job_id, logs=logs, job_config=job_config)

    try:
        # Retrieve logs using the function from core.database (uses g.db_session)
        logs = get_job_logs(job_id, limit=100) # Get recent 100 logs
    except SQLAlchemyError as e:
        logger.error(f"Database error retrieving logs for job '{job_id}': {e}", exc_info=True)
        flash(f"Error retrieving logs for job '{job_id}'.", "error")
    except Exception as e:
        logger.error(f"Unexpected error retrieving logs for job '{job_id}': {e}", exc_info=True)
        flash("An unexpected error occurred.", "error")


    return render_template("job_details.html", job_id=job_id, logs=logs, job_config=job_config)


# Note: Log deletion was originally a GET request, which is bad practice for destructive actions.
# It should be a POST request, ideally triggered by a form/button.
# For Phase 1, we keep the redirect logic but acknowledge it needs changing in Phase 2/3.
@bp.route("/delete_logs/<job_id>", methods=["POST"]) # Changed to POST
def delete_logs(job_id):
    """
    Deletes all logs for a specific job. (Requires POST request)
    """
    session = g.get('db_session')
    if session is None:
        flash("Database connection not available. Cannot delete logs.", "error")
        # Redirect back to job details or index?
        # Redirecting to index might be less confusing if details page relies on DB.
        return redirect(url_for('routes.index'))

    try:
        # Use the core function for deletion
        deleted_count = core_delete_job_logs(job_id)

        if deleted_count >= 0:
            flash(f"Successfully deleted {deleted_count} log(s) for job '{job_id}'.", "success")
        else:
            flash(f"Failed to delete logs for job '{job_id}'. Check scheduler logs.", "error")

    except SQLAlchemyError as e:
        logger.error(f"Database error deleting logs for job '{job_id}': {e}", exc_info=True)
        flash(f"Database error deleting logs for job '{job_id}'.", "error")
    except Exception as e:
        logger.error(f"Unexpected error deleting logs for job '{job_id}': {e}", exc_info=True)
        flash("An unexpected error occurred while deleting logs.", "error")

    # Redirect back to the job details page after deletion attempt
    return redirect(url_for('routes.job_details', job_id=job_id))


# --- Helper Functions ---

def get_schedule_display(job_config: dict) -> str:
    """Generates a display string for the job's schedule."""
    schedule_type = job_config.get("schedule_type", "N/A")
    if schedule_type == "cron":
        return f"Cron: {job_config.get('schedule', 'Not Set')}"
    elif schedule_type == "interval":
        secs = job_config.get('interval_seconds', 'N/A')
        return f"Interval: Every {secs}s"
    elif schedule_type == "date":
        return f"Date: {job_config.get('run_date', 'Not Set')}"
    else:
        return "Schedule: N/A"
