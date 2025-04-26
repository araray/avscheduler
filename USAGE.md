# How to Use AVScheduler

The AVScheduler provides **flexible job scheduling** and **dependency-based execution conditions**. This guide details how to configure and use these features.

---

## **1. Schedule Types**

Jobs can be scheduled using one of the following types defined in your `config.toml` under each `[jobs.<job_id>]` section.

### **1.1. Cron-Based Scheduling**

-   **`schedule_type = "cron"`**
-   Uses standard cron syntax for precise scheduling.
-   Requires the `schedule` key.

#### **Syntax**
```plaintext
* * * * *
- - - - -
| | | | +---- Day of the week (0 - 6 or 7, Sunday = 0 or 7)
| | | +------ Month (1 - 12)
| | +-------- Day of the month (1 - 31)
| +---------- Hour (0 - 23)
+------------ Minute (0 - 59)

Special Characters:
* : Any value
, : Value list separator
- : Range of values
/ : Step values (e.g., */15 for every 15 minutes)
```

#### **Examples**
-   `schedule = "0 * * * *"`: Run at the start of every hour.
-   `schedule = "30 2 * * *"`: Run at 2:30 AM every day.
-   `schedule = "0 0 1 * *"`: Run at midnight on the first day of each month.
-   `schedule = "0 9-17 * * 1-5"`: Run every hour between 9 AM and 5 PM on weekdays (Monday to Friday).

#### **Example Job in `config.toml`**
```toml
[jobs.daily_cleanup]
type = "BASH"
schedule_type = "cron"
schedule = "0 3 * * *"  # Run daily at 3:00 AM
command = "rm /tmp/app_cache/*"
```

---

### **1.2. Interval-Based Scheduling**

-   **`schedule_type = "interval"`**
-   Runs a job repeatedly after a fixed time interval.
-   Requires the `interval_seconds` key.

#### **Example Configurations**
-   **Every 30 minutes**:
    ```toml
    [jobs.check_updates]
    type = "PYTHON"
    schedule_type = "interval"
    interval_seconds = 1800  # 30 minutes * 60 seconds
    command = "python /opt/scripts/update_checker.py"
    ```
-   **Every 2 hours**:
    ```toml
    [jobs.sync_files]
    type = "BASH"
    schedule_type = "interval"
    interval_seconds = 7200  # 2 hours * 3600 seconds
    command = "rsync -av /local/data/ remote_server:/remote/data/"
    ```

---

### **1.3. Date-Based Scheduling**

-   **`schedule_type = "date"`**
-   Runs a job only once at a specific date and time.
-   Requires the `run_date` key in ISO 8601 format (`YYYY-MM-DD HH:MM:SS`).

#### **Example Configuration**
-   **Run on a specific date**:
    ```toml
    [jobs.one_time_migration]
    type = "PYTHON"
    schedule_type = "date"
    run_date = "2025-01-15 10:00:00"  # Run at 10 AM on Jan 15, 2025
    command = "python /opt/scripts/run_migration_v3.py"
    ```

---

## **2. Job Conditions**

-   **`condition = "..."`** (Optional key in `[jobs.<job_id>]`)
-   Allows you to define dependencies between jobs based on the execution history stored in the database.
-   The scheduler evaluates the condition string *before* executing the job. If the condition is false, the job is skipped for that scheduled run.

### **Supported Condition Primitives**

Conditions are built using the format `job_id.check`.

1.  **`<job_id>.last_run_successful`**
    -   Checks if the *most recent* execution log for `<job_id>` has an exit code of `0`.
    -   Returns `False` if the job has never run or the last run failed (non-zero exit code).

    Example:
    ```toml
    # job_B runs only if job_A's last run was successful
    [jobs.job_B]
    # ... schedule, command ...
    condition = "job_A.last_run_successful"
    ```

2.  **`<job_id>.finished_within(X)`**
    -   Checks if the *most recent* execution log for `<job_id>` has an exit code of `0` **AND** its completion timestamp is within the last `X` duration from the current time.
    -   Supported formats for `X`: `Nh` (hours), `Nm` (minutes), `Ns` (seconds). Example: `2h`, `30m`, `90s`.
    -   Returns `False` if the job never ran, the last run failed, or the last successful run finished *before* the calculated cutoff time (`now - X`).

    Example:
    ```toml
    # job_C runs only if job_A finished successfully within the last 2 hours
    [jobs.job_C]
    # ... schedule, command ...
    condition = "job_A.finished_within(2h)"
    ```

### **Combining Conditions**

You can combine multiple condition primitives using logical operators:

-   **`and`**: Both sides must be true.
-   **`or`**: At least one side must be true. (Currently requires careful parsing - simple `and` splitting is implemented first)
-   **`not`**: Negates the result of a condition. (Currently requires careful parsing)

**Note:** The current implementation in `core/conditions.py` primarily supports `and` by splitting the string. More complex logic with `or` and `not` might require enhancements to the parser.

#### **Example: Combined Condition**
```toml
[jobs.generate_report]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 8 * * *"  # Run daily at 8:00 AM
command = "python run_report.py"
# Requires data_etl to have succeeded AND data_validation to have succeeded within 30 mins
condition = "data_etl.last_run_successful and data_validation.finished_within(30m)"
```

-   `generate_report` will only run if:
    1.  `data_etl`'s last execution was successful **AND**
    2.  `data_validation`'s last execution was successful and completed within the last 30 minutes.

### **How Conditions are Evaluated**

-   Conditions are parsed and evaluated by `core/conditions.py`.
-   The evaluation logic queries the `job_execution_logs` table in the SQLite database (`db_path` from `config.toml`).
-   Evaluation happens just before a job's scheduled execution time.

---

## **3. Job Execution Workflow**

1.  **Trigger**: APScheduler triggers a job based on its schedule (`cron`, `interval`, `date`).
2.  **Condition Check**:
    -   The `run_job_wrapper` in `core/scheduler_logic.py` checks if a `condition` is defined for the job.
    -   If yes, `core.conditions.evaluate_condition()` is called.
    -   If `evaluate_condition()` returns `False`, the job run is skipped, and a message is logged.
3.  **Execution**:
    -   If no condition exists or the condition evaluates to `True`, `core.scheduler_logic.execute_job_command()` is called.
    -   This function:
        -   Loads environment variables if `env_file` is specified.
        -   Executes the job's `command` using the specified `type`'s interpreter (from `[interpreters]`).
        -   Uses `subprocess.Popen` to run the command.
        -   Captures `stdout`, `stderr`, and the `exit_code`.
        -   Handles optional `timeout_seconds`.
4.  **Logging**:
    -   After execution (or failure), `core.database.log_job_execution()` is called.
    -   An entry is added to the `job_execution_logs` table with the `job_id`, `exit_code`, `execution_time`, `timestamp`, and captured `stdout`/`stderr`.
    -   Basic execution info is also logged to the scheduler's log file (e.g., `./logs/scheduler.log`).

---

## **4. Interpreters**

-   The `[interpreters]` section in `config.toml` maps job `type` names (case-sensitive) to the absolute path of the executable used to run the job's `command`.
-   Ensure the paths are correct and the user running the scheduler has execute permissions.

```toml
[interpreters]
PYTHON = "/usr/bin/python3"
BASH = "/bin/bash"
NODE = "/usr/local/bin/node"
CUSTOM_SCRIPT = "/opt/my_app/run_script.sh"
```

---

## **5. Managing Logs**

Execution history is stored in the database. You can view and clean up logs using the CLI or Web UI.

### **CLI Commands**

-   **View Logs**:
    ```bash
    # View last 50 logs for all jobs
    python cli.py view-logs

    # View last 20 logs for 'job_1'
    python cli.py view-logs --job-id job_1 --limit 20
    ```

-   **Cleanup Logs**:
    ```bash
    # Delete all logs for 'job_1' (prompts for confirmation)
    python cli.py cleanup-logs job_1 --all

    # Delete logs for 'job_2' older than Dec 1st, 2024 (prompts for confirmation)
    python cli.py cleanup-logs job_2 --before "2024-12-01 00:00:00"
    ```

### **Web UI**

-   Navigate to the **Job Details** page (`/job/<job_id>`).
-   The page displays recent logs.
-   Click the "Delete All Logs" button (requires confirmation) to remove all database log entries for that specific job.

---

This guide provides a comprehensive overview of scheduling, conditions, execution, and log management within AVScheduler. Refer to `config.example.toml` and the main `README.md` for further examples and setup instructions.
