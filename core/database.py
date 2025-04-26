# core/database.py

"""
Database models and interaction logic using SQLAlchemy.
"""

import os
import logging
from datetime import datetime
import sqlite3 # Keep for direct queries if needed, e.g., in conditions

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, MetaData
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Define the base class for declarative models
Base = declarative_base()

# --- SQLAlchemy Models ---

class JobExecutionLog(Base):
    """
    SQLAlchemy model for the job_execution_logs table.
    Stores history of individual job runs.
    """
    __tablename__ = "job_execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=False, index=True) # Added index
    exit_code = Column(Integer, nullable=False)
    execution_time = Column(Float, nullable=False) # Duration in seconds
    timestamp = Column(DateTime, nullable=False, default=datetime.now, index=True) # Added index
    stdout = Column(Text, nullable=True) # Store stdout
    stderr = Column(Text, nullable=True) # Store stderr

    def __repr__(self):
        return (f"<JobExecutionLog(id={self.id}, job_id='{self.job_id}', "
                f"exit_code={self.exit_code}, timestamp='{self.timestamp}')>")


# --- Database Initialization and Session Management ---

# Global engine and session factory (initialize lazily)
_engine = None
_SessionFactory = None

def init_db(db_path: str):
    """
    Initializes the database engine, creates tables if they don't exist,
    and sets up the session factory.

    Args:
        db_path: The path to the SQLite database file.
    """
    global _engine, _SessionFactory
    if _engine is not None:
        logger.warning("Database engine already initialized.")
        return

    try:
        # Ensure the directory for the database exists
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

        logger.info(f"Initializing database at: {db_path}")
        _engine = create_engine(f"sqlite:///{db_path}")

        # Create tables defined by SQLAlchemy models
        Base.metadata.create_all(_engine)
        logger.info("Database tables checked/created successfully.")

        # Create a session factory
        _SessionFactory = sessionmaker(bind=_engine)
        logger.info("Database session factory created.")

    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database engine or tables: {e}", exc_info=True)
        _engine = None # Reset on failure
        _SessionFactory = None
        raise # Re-raise the exception
    except OSError as e:
        logger.error(f"Failed to create database directory '{db_dir}': {e}", exc_info=True)
        raise

def get_session():
    """
    Provides a database session from the session factory.

    Returns:
        A SQLAlchemy Session object.

    Raises:
        RuntimeError: If the database is not initialized (init_db was not called or failed).
    """
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionFactory()

# --- Database Operations ---

def log_job_execution(job_id: str, exit_code: int, execution_time: float, stdout: str = None, stderr: str = None):
    """
    Logs the details of a job execution to the database.

    Args:
        job_id: The unique identifier of the job.
        exit_code: The exit code returned by the job process.
        execution_time: The time taken for the job to execute in seconds.
        stdout: The standard output captured from the job (optional).
        stderr: The standard error captured from the job (optional).
    """
    session = get_session()
    try:
        log_entry = JobExecutionLog(
            job_id=job_id,
            exit_code=exit_code,
            execution_time=execution_time,
            timestamp=datetime.now(), # Ensure timestamp is set here
            stdout=stdout,
            stderr=stderr
        )
        session.add(log_entry)
        session.commit()
        logger.debug(f"Logged execution for job '{job_id}' (Exit: {exit_code})")
    except SQLAlchemyError as e:
        logger.error(f"Failed to log job execution for '{job_id}': {e}", exc_info=True)
        session.rollback() # Rollback on error
    except Exception as e:
        logger.error(f"Unexpected error logging job execution for '{job_id}': {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()

def get_job_logs(job_id: str, limit: int = 50):
    """
    Retrieves execution logs for a specific job, ordered by timestamp descending.

    Args:
        job_id: The ID of the job to retrieve logs for.
        limit: The maximum number of log entries to return.

    Returns:
        A list of JobExecutionLog objects, or an empty list if none found or on error.
    """
    session = get_session()
    try:
        logs = session.query(JobExecutionLog)\
                      .filter(JobExecutionLog.job_id == job_id)\
                      .order_by(JobExecutionLog.timestamp.desc())\
                      .limit(limit)\
                      .all()
        return logs
    except SQLAlchemyError as e:
        logger.error(f"Failed to retrieve logs for job '{job_id}': {e}", exc_info=True)
        return [] # Return empty list on error
    finally:
        session.close()

def get_latest_job_log(job_id: str):
    """
    Retrieves the most recent execution log for a specific job.

    Args:
        job_id: The ID of the job.

    Returns:
        The latest JobExecutionLog object, or None if no logs exist or on error.
    """
    session = get_session()
    try:
        latest_log = session.query(JobExecutionLog)\
                            .filter(JobExecutionLog.job_id == job_id)\
                            .order_by(JobExecutionLog.timestamp.desc())\
                            .first()
        return latest_log
    except SQLAlchemyError as e:
        logger.error(f"Failed to retrieve latest log for job '{job_id}': {e}", exc_info=True)
        return None # Return None on error
    finally:
        session.close()

def delete_job_logs(job_id: str, before_timestamp: datetime = None):
    """
    Deletes logs for a specific job, optionally before a given timestamp.

    Args:
        job_id: The ID of the job whose logs should be deleted.
        before_timestamp: If provided, only logs older than this timestamp will be deleted.
                          If None, all logs for the job will be deleted.

    Returns:
        The number of logs deleted, or -1 on error.
    """
    session = get_session()
    try:
        query = session.query(JobExecutionLog).filter(JobExecutionLog.job_id == job_id)
        if before_timestamp:
            query = query.filter(JobExecutionLog.timestamp < before_timestamp)

        deleted_count = query.delete(synchronize_session=False) # Efficient delete
        session.commit()
        logger.info(f"Deleted {deleted_count} log(s) for job '{job_id}'"
                    f"{' before ' + str(before_timestamp) if before_timestamp else ''}.")
        return deleted_count
    except SQLAlchemyError as e:
        logger.error(f"Failed to delete logs for job '{job_id}': {e}", exc_info=True)
        session.rollback()
        return -1 # Indicate error
    finally:
        session.close()

def get_distinct_job_ids():
    """
    Retrieves a list of unique job IDs that have execution logs.

    Returns:
        A list of distinct job ID strings, or an empty list on error.
    """
    session = get_session()
    try:
        # Query distinct job_id values
        distinct_ids = session.query(JobExecutionLog.job_id).distinct().all()
        # Extract the job_id string from each tuple in the result
        return [job_id[0] for job_id in distinct_ids]
    except SQLAlchemyError as e:
        logger.error(f"Failed to retrieve distinct job IDs: {e}", exc_info=True)
        return [] # Return empty list on error
    finally:
        session.close()

# --- Direct SQLite Connection (for condition evaluation, potentially faster) ---
# This is kept for compatibility with the existing condition parser,
# but ideally, condition evaluation could also use SQLAlchemy if performance allows.

def query_last_run_status(job_id: str, db_path: str) -> tuple | None:
    """
    Directly queries SQLite for the last run status (timestamp, exit_code) of a job.

    Args:
        job_id: The ID of the job.
        db_path: Path to the SQLite database file.

    Returns:
        A tuple (timestamp_iso_string, exit_code) or None if no log found or error.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, exit_code FROM job_execution_logs
            WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1
            """,
            (job_id,),
        )
        result = cursor.fetchone()
        return result # Returns (timestamp_str, exit_code) or None
    except sqlite3.Error as e:
        logger.error(f"Direct DB query failed for last run status of '{job_id}': {e}")
        return None
    finally:
        if conn:
            conn.close()
