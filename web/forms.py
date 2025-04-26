# web/forms.py

"""
Defines WTForms for the AVScheduler web interface.
"""

from flask_wtf import FlaskForm
from wtforms import (
    StringField, SelectField, IntegerField, DateTimeField,
    TextAreaField, SubmitField, ValidationError, BooleanField
)
from wtforms.validators import DataRequired, Optional, Length, Regexp, NumberRange
from datetime import datetime
import croniter # Used for basic cron validation

class JobForm(FlaskForm):
    """Form for adding and editing scheduler jobs."""

    # Basic Job Info
    job_id = StringField(
        'Job ID',
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(r'^[a-zA-Z0-9_-]+$', message="Job ID can only contain letters, numbers, underscores, and hyphens.")
        ],
        description="Unique identifier for the job (e.g., 'daily_backup', 'report_job_1'). Cannot be changed after creation."
    )
    name = StringField(
        'Display Name (Optional)',
        validators=[Optional(), Length(max=150)],
        description="A user-friendly name for display purposes."
    )
    job_type = SelectField( # Renamed from 'type' to avoid conflict with Python keyword
        'Job Type',
        validators=[DataRequired()],
        choices=[], # Populated dynamically in the route
        description="Select the interpreter type (defined in config [interpreters])."
    )
    command = TextAreaField(
        'Command',
        validators=[DataRequired()],
        render_kw={"rows": 5},
        description="The command string to be executed by the selected interpreter."
    )

    # Scheduling Info
    schedule_type = SelectField(
        'Schedule Type',
        validators=[DataRequired()],
        choices=[
            ('cron', 'Cron'),
            ('interval', 'Interval'),
            ('date', 'Date (One-time)')
        ],
        default='cron',
        description="Choose how the job should be triggered."
    )
    schedule = StringField(
        'Cron Schedule',
        validators=[Optional()], # Required only if schedule_type is 'cron'
        description="Standard cron format (e.g., '0 * * * *' for hourly). Required for 'Cron' type."
    )
    interval_seconds = IntegerField(
        'Interval (Seconds)',
        validators=[Optional(), NumberRange(min=1)], # Required only if schedule_type is 'interval'
        description="Run every X seconds. Required for 'Interval' type."
    )
    run_date = DateTimeField(
        'Run Date (YYYY-MM-DD HH:MM:SS)',
        validators=[Optional()], # Required only if schedule_type is 'date'
        format='%Y-%m-%d %H:%M:%S',
        description="Specific date and time for one-time execution. Required for 'Date' type."
    )

    # Advanced Options
    condition = StringField(
        'Condition (Optional)',
        validators=[Optional(), Length(max=500)],
        description="Dependency condition (e.g., 'other_job.last_run_successful'). See USAGE.md."
    )
    env_file = StringField(
        'Environment File Path (Optional)',
        validators=[Optional(), Length(max=500)],
        description="Absolute path to a .env file for this job."
    )
    timeout_seconds = IntegerField(
        'Timeout (Seconds, Optional)',
        validators=[Optional(), NumberRange(min=1)],
        description="Maximum execution time before the job is terminated."
    )
    misfire_grace_time = IntegerField(
        'Misfire Grace Time (Seconds, Optional)',
        validators=[Optional(), NumberRange(min=1)],
        description="Seconds after scheduled time the job can still run (default: APScheduler's default)."
    )
    coalesce = BooleanField(
        'Coalesce Missed Runs',
        default=True, # Match APScheduler default
        description="Run once if multiple runs were missed (checked) or run for every missed instance (unchecked)."
    )
    max_instances = IntegerField(
        'Max Concurrent Instances',
        default=1, # Match APScheduler default
        validators=[Optional(), NumberRange(min=1)],
        description="Maximum number of instances of this job allowed to run concurrently."
    )

    # Submit Button
    submit = SubmitField('Save Job')

    # --- Custom Validation ---

    def validate_schedule(form, field):
        """Validate cron schedule string if type is 'cron'."""
        if form.schedule_type.data == 'cron':
            if not field.data:
                raise ValidationError('Cron schedule is required for schedule type "Cron".')
            try:
                # Use croniter for basic syntax validation
                croniter.croniter.is_valid(field.data)
            except ValueError as e:
                raise ValidationError(f"Invalid cron format: {e}")
            except Exception as e: # Catch potential other errors from croniter
                raise ValidationError(f"Error validating cron schedule: {e}")

    def validate_interval_seconds(form, field):
        """Validate interval seconds if type is 'interval'."""
        if form.schedule_type.data == 'interval':
            if field.data is None: # Check for None explicitly
                raise ValidationError('Interval seconds is required for schedule type "Interval".')
            if field.data <= 0:
                 raise ValidationError('Interval must be a positive number of seconds.')

    def validate_run_date(form, field):
        """Validate run date if type is 'date'."""
        if form.schedule_type.data == 'date':
            if not field.data:
                raise ValidationError('Run date is required for schedule type "Date".')
            # WTForms DateTimeField with format handles basic validation
            # Add check to ensure date is in the future? Optional.
            # if field.data <= datetime.now():
            #     raise ValidationError("Run date must be in the future.")

    # Note: Validation for env_file path existence should ideally be done in the route
    # after submission, as the web server process might not have the same filesystem view
    # or permissions as the user or scheduler process.
