# core/conditions.py

"""
Condition parsing and evaluation logic for job dependencies.
"""

import sqlite3
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def evaluate_condition(condition_str: str, db_path: str, current_job_id: str) -> bool:
    """
    Evaluate a complex condition string using job execution logs from the database.

    Args:
        condition_str: The condition string (e.g., "job_1.last_run_successful and job_2.finished_within(2h)").
        db_path: Path to the SQLite database file.
        current_job_id: The ID of the job whose condition is being evaluated (for context, not used directly in evaluation yet).

    Returns:
        True if the condition is met, False otherwise.
    """
    if not condition_str:
        return True  # No condition means it's always met

    logger.info(f"Evaluating condition for job '{current_job_id}': {condition_str}")

    # Basic parsing (can be enhanced with a proper parsing library like pyparsing for complex logic)
    # For now, handle simple 'and', 'or', 'not' and direct checks
    # This implementation assumes conditions are simple and focuses on the core checks.
    # A more robust parser would be needed for complex boolean logic.

    # Example: Split by 'and' and evaluate each part (simplistic approach)
    parts = condition_str.split(' and ') # TODO: Add support for 'or', 'not', parentheses
    all_met = True
    for part in parts:
        part = part.strip()
        if not _evaluate_single_condition_part(part, db_path):
            all_met = False
            break

    logger.info(f"Condition evaluation result for job '{current_job_id}': {all_met}")
    return all_met

def _evaluate_single_condition_part(condition_part: str, db_path: str) -> bool:
    """
    Evaluates a single part of a condition string (e.g., "job_1.last_run_successful").

    Args:
        condition_part: The single condition part string.
        db_path: Path to the SQLite database file.

    Returns:
        True if the single condition part is met, False otherwise.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        if ".last_run_successful" in condition_part:
            job_id = condition_part.split(".")[0]
            cursor.execute(
                """
                SELECT exit_code FROM job_execution_logs
                WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1
                """,
                (job_id,),
            )
            result = cursor.fetchone()
            # Condition met if a successful run (exit code 0) exists
            met = result is not None and result[0] == 0
            logger.debug(f"Condition '{condition_part}': Last run successful? {met} (Result: {result})")
            return met

        elif ".finished_within(" in condition_part:
            # Example: job_2.finished_within(2h)
            job_id_part, time_part = condition_part.split(".finished_within(")
            job_id = job_id_part.strip()
            time_str = time_part.strip()[:-1] # Remove trailing ')'

            try:
                time_delta = parse_time_string(time_str)
                cutoff_time = datetime.now() - time_delta
                logger.debug(f"Condition '{condition_part}': Checking if finished after {cutoff_time.isoformat()}")
            except ValueError as e:
                logger.error(f"Invalid time format in condition '{condition_part}': {e}")
                return False # Invalid time string

            cursor.execute(
                """
                SELECT timestamp, exit_code FROM job_execution_logs
                WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1
                """,
                (job_id,),
            )
            result = cursor.fetchone()
            # Condition met if a successful run (exit code 0) finished after the cutoff time
            met = (
                result is not None and
                result[1] == 0 and # Check exit code is 0
                datetime.fromisoformat(result[0]) >= cutoff_time
            )
            logger.debug(f"Condition '{condition_part}': Finished within time? {met} (Result: {result})")
            return met

        else:
            logger.warning(f"Unsupported condition format: {condition_part}")
            return False # Unsupported condition type

    except sqlite3.Error as e:
        logger.error(f"Database error while evaluating condition '{condition_part}': {e}")
        return False # Treat database errors as condition failure
    except Exception as e:
        logger.error(f"Unexpected error while evaluating condition '{condition_part}': {e}")
        return False # Treat other errors as condition failure
    finally:
        if conn:
            conn.close()


def parse_time_string(time_str: str) -> timedelta:
    """
    Parse a human-readable time string (e.g., "2h", "30m", "10s") into a timedelta object.

    Args:
        time_str: The time string to parse.

    Returns:
        A timedelta object representing the duration.

    Raises:
        ValueError: If the time string format is invalid.
    """
    time_str = time_str.lower().strip()
    if time_str.endswith("h"):
        return timedelta(hours=int(time_str[:-1]))
    elif time_str.endswith("m"):
        return timedelta(minutes=int(time_str[:-1]))
    elif time_str.endswith("s"):
        return timedelta(seconds=int(time_str[:-1]))
    else:
        raise ValueError(f"Invalid time format: '{time_str}'. Use 'h', 'm', or 's'.")
