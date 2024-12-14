import sqlite3
from datetime import datetime, timedelta

def evaluate_condition(condition, db_path, current_job_id):
    """
    Evaluate a condition expression using SQLite and job execution logs.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Parse condition: example -> "job_1.last_run_successful and job_1.finished_within(2h)"
    if "last_run_successful" in condition:
        job_id = condition.split(".")[0]
        cursor.execute(
            """
            SELECT exit_code FROM job_execution_logs
            WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1
            """,
            (job_id,),
        )
        result = cursor.fetchone()
        if result is None or result[0] != 0:
            return False

    if "finished_within" in condition:
        job_id, time_str = condition.split(".")[0], condition.split("(")[1][:-1]
        time_delta = parse_time_string(time_str)
        cutoff_time = datetime.now() - time_delta

        cursor.execute(
            """
            SELECT timestamp FROM job_execution_logs
            WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1
            """,
            (job_id,),
        )
        result = cursor.fetchone()
        if result is None or datetime.fromisoformat(result[0]) < cutoff_time:
            return False

    conn.close()
    return True

def parse_time_string(time_str):
    """
    Parse a human-readable time string into a timedelta object.
    """
    if time_str.endswith("h"):
        return timedelta(hours=int(time_str[:-1]))
    elif time_str.endswith("m"):
        return timedelta(minutes=int(time_str[:-1]))
    elif time_str.endswith("s"):
        return timedelta(seconds=int(time_str[:-1]))
    return timedelta()
