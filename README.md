# **AVScheduler Tool**

A Python-based job scheduler designed to dynamically manage, execute, and monitor scheduled tasks with dependency-based execution, detailed logging, and a powerful web interface and CLI.

---

## **Table of Contents**

1.  [Features](#features)
2.  [Installation](#installation)
3.  [Configuration (`config.toml`)](#configuration-configtoml)
    * [`[settings]`](#settings-section)
    * [`[web_server]`](#web_server-section)
    * [`[interpreters]`](#interpreters-section)
    * [`[jobs.<job_id>]`](#jobsjob_id-section)
    * [Schedule Types](#schedule-types)
    * [Job Conditions](#job-conditions)
4.  [Command Line Interface (CLI)](#command-line-interface-cli)
    * [Daemon Commands](#daemon-commands)
    * [Job & Log Commands (CLI)](#job--log-commands-cli)
    * [CLI Examples](#cli-examples)
5.  [Web Interface](#web-interface)
    * [Accessing the UI](#accessing-the-ui)
    * [Dashboard](#dashboard)
    * [Job Details & Logs](#job-details--logs)
    * [Adding/Editing/Deleting Jobs (Web UI)](#addingeditingdeleting-jobs-web-ui)
6.  [Job Execution Details](#job-execution-details)
7.  [System Integration (Systemd)](#system-integration-systemd)
8.  [Database Schema](#database-schema)
9.  [Contributing](#contributing)
10. [License](#license)

---

## **1. Features**

-   **Flexible Scheduling**:
    -   Supports **cron-like schedules**, **interval-based scheduling**, and **date-based triggers**.
    -   Define jobs with dependencies to execute only when conditions are met.
-   **Dependency Management**:
    -   Jobs can have conditions based on the status and timing of other jobs (e.g., `job_A.last_run_successful`, `job_B.finished_within(2h)`).
-   **Dynamic Management**:
    -   Use the **CLI** or **Web Interface** to add, edit, delete, or manually run jobs dynamically.
    -   Configuration changes made via the Web UI automatically trigger a reload in the running daemon and update the UI's view. CLI changes require a manual `reload-config` or `restart`.
    -   Optionally auto-generate unique Job IDs when adding via the Web UI.
-   **Powerful Logging**:
    -   Logs every job execution to a database, including:
        -   **Timestamps**
        -   **Execution time**
        -   **Exit code**
        -   **Stdout/Stderr** (optional)
    -   View and manage logs via the CLI or Web Interface.
-   **Web Interface**:
    -   View job statuses, configurations, and execution history.
    -   Add, edit, and delete job definitions through intuitive forms.
    -   View and delete execution logs per job.
-   **CLI**:
    -   Fully-featured CLI for daemon management, job execution, configuration management, and log viewing/cleanup.
-   **Systemd Integration**:
    -   Easily run the scheduler as a background service with automatic startup and management.

---

## **2. Installation**

### **Prerequisites**

-   **Python**: 3.11 or higher.
-   **SQLite**: Default database (usually included with Python).
-   Required Python packages (see `requirements.txt`). Includes `APScheduler`, `Flask`, `Flask-WTF`, `SQLAlchemy`, `toml`, `click`, `croniter`, etc.
-   Recommended: A **virtual environment** for dependency isolation.

### **Step 1: Clone the Repository**

```bash
git clone [https://github.com/araray/avscheduler.git](https://github.com/araray/avscheduler.git)
cd avscheduler
````

### **Step 2: Install Dependencies**

```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate # On Windows use `venv\Scripts\activate`

# Install requirements
pip install -r requirements.txt
```

### **Step 3: Configure**

  - Copy `config.example.toml` to `config.toml`.
  - Edit `config.toml` to set your `db_path`, `pid_file`, interpreters, and define initial jobs.
  - **Important:** Ensure the directories for `db_path` and `pid_file` exist or are writable by the user running the scheduler.

### **Step 4: Initialize the Database (Optional but Recommended)**

While SQLAlchemy creates tables automatically on first run, you might want to ensure the DB file exists initially if permissions are strict.

```bash
# This step might not be strictly necessary if using SQLAlchemy's create_all
# touch /path/to/your/jobs.db # Ensure the file exists if needed by init_db permissions
```

-----

## **3. Configuration (`config.toml`)**

All scheduler settings, job definitions, and interpreters are stored in a **TOML configuration file** (default: `config.toml`).

### **Example `config.toml`**

```toml
[settings]
# Path to the SQLite database file. Directory must exist.
db_path = "/var/lib/avscheduler/jobs.db"
# Path to store the daemon's PID file. Directory must exist.
pid_file = "/var/run/avscheduler/avscheduler.pid"
# Optional: Sampling interval for internal metrics (if implemented)
# sampling_interval = 1000

[web_server]
host = "127.0.0.1"
port = 5000 # Default Flask port

[interpreters]
PYTHON = "/usr/bin/python3" # Or path from `which python3`
BASH = "/bin/bash"
NODE = "/usr/local/bin/node" # Example

# --- Job Definitions ---
# Job ID (e.g., job_1) must be unique. Can be auto-generated via Web UI.

[jobs.job_1]
name = "Hourly Python Job" # Optional display name
type = "PYTHON"
schedule_type = "cron"
schedule = "10 * * * *" # Every hour at minute 10
command = "print('Hello from Job 1!')"
condition = "job_2.last_run_successful and job_2.finished_within(2h)"
# Optional: Timeout in seconds for this job
timeout_seconds = 300
# Optional: Path to a file with environment variables
env_file = "/path/to/job1.env"
# Optional: Max concurrent runs
max_instances = 1
# Optional: Coalesce missed runs
coalesce = true
# Optional: Misfire grace time (seconds)
misfire_grace_time = 60


[jobs.job_2]
name = "Hourly Bash Job"
type = "BASH"
schedule_type = "interval"
interval_seconds = 3600  # Every hour
command = "echo 'Running Job 2! Exit code 0.'"

[jobs.failing_job]
type = "BASH"
schedule_type = "interval"
interval_seconds = 1800 # Every 30 mins
command = "echo 'This job will fail'; exit 1"

[jobs.one_time_task]
type = "PYTHON"
schedule_type = "date"
run_date = "2025-12-31 23:59:00" # Specific date/time
command = "python /opt/scripts/cleanup_script.py --final"
```

-----

### **Configuration Sections**

#### **`[settings]` Section**

| Key                 | Description                                                    | Default (if not set)     |
| :------------------ | :------------------------------------------------------------- | :----------------------- |
| `db_path`           | Path to the SQLite database file. **Directory must exist.** | `./jobs.db`              |
| `pid_file`          | Path to store the daemon's PID file. **Directory must exist.** | `./logs/avscheduler.pid` |
| `sampling_interval` | (Currently unused) Interval for internal metrics sampling.     | `1000`                   |

#### **`[web_server]` Section**

| Key    | Description                       | Default     |
| :----- | :-------------------------------- | :---------- |
| `host` | IP address for the web interface. | `127.0.0.1` |
| `port` | Port for the web interface.       | `5000`      |

#### **`[interpreters]` Section**

Maps job `type` names (case-sensitive) to the absolute path of the executable used to run the job's `command`. Ensure the paths are correct and the user running the scheduler has execute permissions.

```toml
[interpreters]
PYTHON = "/usr/bin/python3"
BASH = "/bin/bash"
NODE = "/usr/local/bin/node"
CUSTOM_SCRIPT = "/opt/my_app/run_script.sh"
```

#### **`[jobs.<job_id>]` Section**

Defines an individual job. The `<job_id>` is the unique identifier (e.g., `job_1`, `daily_report`, `8a3fec01`). This ID can be provided manually or auto-generated via the Web UI.

| Key                 | Description                                                                                             | Required?                                |
| :------------------ | :------------------------------------------------------------------------------------------------------ | :--------------------------------------- |
| `type`              | Type of job (e.g., `PYTHON`, `BASH`). Must match a key in `[interpreters]`.                             | Yes                                      |
| `schedule_type`     | `cron`, `interval`, or `date`.                                                                          | Yes                                      |
| `command`           | Command string to execute.                                                                              | Yes                                      |
| `schedule`          | Cron schedule string (e.g., `0 * * * *`). See [Schedule Types](https://www.google.com/search?q=%23schedule-types).                         | If `schedule_type` is `cron`             |
| `interval_seconds`  | Interval in seconds. See [Schedule Types](https://www.google.com/search?q=%23schedule-types).                                             | If `schedule_type` is `interval`         |
| `run_date`          | Specific date/time (ISO format: `YYYY-MM-DD HH:MM:SS`). See [Schedule Types](https://www.google.com/search?q=%23schedule-types).          | If `schedule_type` is `date`             |
| `name`              | (Optional) Display name for the job (defaults to `job_id`).                                             | No                                       |
| `condition`         | (Optional) Execution condition based on other jobs' status. See [Job Conditions](https://www.google.com/search?q=%23job-conditions).      | No                                       |
| `env_file`          | (Optional) Absolute path to a `.env` file to load environment variables from.                           | No                                       |
| `timeout_seconds`   | (Optional) Maximum execution time in seconds before the job is terminated.                              | No                                       |
| `misfire_grace_time`| (Optional) Seconds after the scheduled run time that the job is allowed to start.                       | No (APScheduler default, often 60s)      |
| `coalesce`          | (Optional) Run missed executions only once (`true`) or for every missed run (`false`).                    | No (APScheduler default: `true`)         |
| `max_instances`     | (Optional) Maximum number of concurrent instances of the job.                                           | No (APScheduler default: `1`)            |

-----

### **Schedule Types**

Jobs can be scheduled using one of the following types defined by the `schedule_type` key in your `config.toml` under each `[jobs.<job_id>]` section.

#### **1. Cron-Based Scheduling (`schedule_type = "cron"`)**

  - Uses standard cron syntax for precise scheduling.
  - Requires the `schedule` key.

**Syntax:**

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

**Examples:**

  - `schedule = "0 * * * *"`: Run at the start of every hour.
  - `schedule = "30 2 * * *"`: Run at 2:30 AM every day.
  - `schedule = "0 0 1 * *"`: Run at midnight on the first day of each month.
  - `schedule = "0 9-17 * * 1-5"`: Run every hour between 9 AM and 5 PM on weekdays (Monday to Friday).

#### **2. Interval-Based Scheduling (`schedule_type = "interval"`)**

  - Runs a job repeatedly after a fixed time interval.
  - Requires the `interval_seconds` key.

**Examples:**

  - **Every 30 minutes**: `interval_seconds = 1800`
  - **Every 2 hours**: `interval_seconds = 7200`

#### **3. Date-Based Scheduling (`schedule_type = "date"`)**

  - Runs a job only once at a specific date and time.
  - Requires the `run_date` key in ISO 8601 format (`YYYY-MM-DD HH:MM:SS`).

**Example:**

  - **Run on a specific date**: `run_date = "2025-01-15 10:00:00"`

-----

### **Job Conditions**

  - **`condition = "..."`** (Optional key in `[jobs.<job_id>]`)
  - Allows you to define dependencies between jobs based on the execution history stored in the database.
  - The scheduler evaluates the condition string *before* executing the job. If the condition is false, the job is skipped for that scheduled run.

#### **Supported Condition Primitives**

Conditions are built using the format `job_id.check`.

1.  **`<job_id>.last_run_successful`**

      - Checks if the *most recent* execution log for `<job_id>` has an exit code of `0`.
      - Returns `False` if the job has never run or the last run failed (non-zero exit code).

    Example:

    ```toml
    # job_B runs only if job_A's last run was successful
    [jobs.job_B]
    # ... schedule, command ...
    condition = "job_A.last_run_successful"
    ```

2.  **`<job_id>.finished_within(X)`**

      - Checks if the *most recent* execution log for `<job_id>` has an exit code of `0` **AND** its completion timestamp is within the last `X` duration from the current time.
      - Supported formats for `X`: `Nh` (hours), `Nm` (minutes), `Ns` (seconds). Example: `2h`, `30m`, `90s`.
      - Returns `False` if the job never ran, the last run failed, or the last successful run finished *before* the calculated cutoff time (`now - X`).

    Example:

    ```toml
    # job_C runs only if job_A finished successfully within the last 2 hours
    [jobs.job_C]
    # ... schedule, command ...
    condition = "job_A.finished_within(2h)"
    ```

#### **Combining Conditions**

You can combine multiple condition primitives using logical operators:

  - **`and`**: Both sides must be true.
  - **`or`**: At least one side must be true. (*Note: Current parser in `core/conditions.py` primarily supports `and` by splitting. Complex logic with `or`/`not`/parentheses may require parser enhancements.*)
  - **`not`**: Negates the result of a condition. (*See note above.*)

**Example: Combined Condition**

```toml
[jobs.generate_report]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 8 * * *"  # Run daily at 8:00 AM
command = "python run_report.py"
# Requires data_etl to have succeeded AND data_validation to have succeeded within 30 mins
condition = "data_etl.last_run_successful and data_validation.finished_within(30m)"
```

  - `generate_report` will only run if:
    1.  `data_etl`'s last execution was successful **AND**
    2.  `data_validation`'s last execution was successful and completed within the last 30 minutes.

#### **How Conditions are Evaluated**

  - Conditions are parsed and evaluated by `core/conditions.py`.
  - The evaluation logic queries the `job_execution_logs` table in the SQLite database (`db_path` from `config.toml`).
  - Evaluation happens just before a job's scheduled execution time.

-----

## **4. Command Line Interface (CLI)**

The CLI allows you to manage the scheduler daemon, jobs, and logs.

### **Run the CLI**

```bash
# Ensure your virtual environment is active
# source venv/bin/activate

# Run using python
python cli.py [OPTIONS] COMMAND [ARGS]...

# Or using the wrapper script (if executable and in PATH)
# ./avscheduler [OPTIONS] COMMAND [ARGS]...
```

Specify the config file using `-c` or `--config` if it's not in the default location (`./config.toml`).

### **Daemon Commands**

| Command         | Description                                                                    |
| :-------------- | :----------------------------------------------------------------------------- |
| `start`         | Start the scheduler process in the foreground. **Use a process manager like systemd for background execution.** |
| `stop`          | Stop the running scheduler daemon process (using the PID file).                |
| `status`        | Check the status of the scheduler daemon (using the PID file).                 |
| `restart`       | Stop and then start the scheduler daemon (runs foreground after restart).      |
| `reload-config` | Signal the running daemon to reload the configuration file (sends `SIGHUP`).   |

### **Job & Log Commands (CLI)**

| Command        | Description                                                              | Notes                                                                 |
| :------------- | :----------------------------------------------------------------------- | :-------------------------------------------------------------------- |
| `list-jobs`    | List all jobs defined in the configuration and their last log status.    |                                                                       |
| `run-job`      | Manually run a specific job by its ID, bypassing schedule and conditions. | Logs execution to DB.                                                 |
| `add-job`      | Add a new job definition to the configuration file.                      | Requires `reload-config` or `restart` to take effect in daemon.       |
| `edit-job`     | Edit properties of an existing job in the configuration file.            | Requires `reload-config` or `restart` to take effect in daemon.       |
| `delete-job`   | Delete a job definition from the configuration file.                     | Requires `reload-config` or `restart` to take effect in daemon.       |
| `view-logs`    | View job execution logs from the database. Supports filtering.           | Use `--job-id`, `--limit`, `--since`, `--until`, `--exit-code`.       |
| `cleanup-logs` | Delete execution logs for a specific job. Supports filters.              | Use `--job-id`, `--before`, `--all`. Requires confirmation.           |

**Note:** The Web UI provides alternative methods for managing jobs (add/edit/delete) and viewing/deleting logs, including automatic daemon reloading for changes made via the UI.

### **CLI Examples**

1.  **Start the Scheduler (Foreground)**:

    ```bash
    python cli.py --config /path/to/your/config.toml start
    ```

    *(For background, see [Systemd](https://www.google.com/search?q=%23system-integration-systemd) section)*

2.  **Check Status**:

    ```bash
    python cli.py status
    ```

3.  **List All Jobs**:

    ```bash
    python cli.py list-jobs
    ```

4.  **Run a Job Manually**:

    ```bash
    python cli.py run-job job_1
    ```

5.  **View Logs for a Specific Job (Last 10)**:

    ```bash
    python cli.py view-logs --job-id job_2 --limit 10
    ```

6.  **Add a New Job (then reload)**:

    ```bash
    # Add the job definition to config.toml
    python cli.py add-job new_job --type PYTHON --schedule-type interval --interval-seconds 60 --command "print('New job running')"

    # Signal the running daemon to reload
    python cli.py reload-config
    ```

7.  **Delete Old Logs**:

    ```bash
    python cli.py cleanup-logs job_1 --before "2024-12-01 00:00:00"
    ```

-----

## **5. Web Interface**

The web interface provides a dashboard to monitor job status, view execution logs, and manage job definitions.

### **Accessing the UI**

1.  Start the scheduler daemon (e.g., using `systemd` or `python cli.py start`).
2.  Ensure the `host` and `port` in the `[web_server]` section of your `config.toml` are correctly set.
3.  Navigate your browser to `http://<host>:<port>` (e.g., `http://127.0.0.1:5000`).

### **Dashboard (`/`)**

  - View all jobs listed in the configuration.
  - See the last execution timestamp, exit code, and duration from the logs.
  - View the configured schedule, condition, and type.
  - See the next scheduled run time (fetched from the running scheduler).
  - Buttons to **Add**, **Edit**, or **Delete** jobs.

### **Job Details & Logs (`/job/<job_id>`)**

  - View the full configuration details for the specific job.
  - See a table of recent execution logs (timestamp, exit code, duration, stdout/stderr snippet).
  - Button to delete all logs for that specific job (requires confirmation).

### **Adding/Editing/Deleting Jobs (Web UI)**

  - Use the "Add New Job" button on the dashboard or the "Edit" button for an existing job to access the job form (`/jobs/add` or `/jobs/edit/<job_id>`).
  - Fill in the job details (ID, type, schedule, command, etc.).
      - Job ID can be left blank when adding to auto-generate a unique ID.
      - Job ID cannot be changed when editing.
  - Saving the form updates the `config.toml` file and automatically signals the running daemon to reload the configuration. The Web UI's view is also updated.
  - Use the "Delete" button (requires confirmation) on the dashboard to remove a job definition from the configuration and signal the daemon.

*(Screenshots could be added here)*

-----

## **6. Job Execution Details**

This section describes the workflow when a job is triggered.

1.  **Trigger**: APScheduler triggers a job based on its schedule (`cron`, `interval`, `date`).
2.  **Condition Check**:
      - The `run_job_wrapper` in `core/scheduler_logic.py` checks if a `condition` is defined for the job in the current configuration.
      - If yes, `core.conditions.evaluate_condition()` is called, querying the database.
      - If `evaluate_condition()` returns `False`, the job run is skipped, and a message is logged.
3.  **Execution**:
      - If no condition exists or the condition evaluates to `True`, `core.scheduler_logic.execute_job_command()` is called.
      - This function:
          - Loads environment variables if `env_file` is specified.
          - Executes the job's `command` using the specified `type`'s interpreter (from `[interpreters]`).
          - Uses `subprocess.Popen` to run the command.
          - Captures `stdout`, `stderr`, and the `exit_code`.
          - Handles optional `timeout_seconds`.
4.  **Logging**:
      - After execution (or failure/skip), `core.database.log_job_execution()` is called.
      - An entry is added to the `job_execution_logs` table with the `job_id`, `exit_code`, `execution_time`, `timestamp`, and captured `stdout`/`stderr`.
      - Basic execution info is also logged to the scheduler's main log file (e.g., `./logs/scheduler.log`).

-----

## **7. System Integration (Systemd)**

Integrate the scheduler with **systemd** for robust background execution, automatic startup, and process management.

### **Example Service File (`/etc/systemd/system/avscheduler.service`)**

```ini
[Unit]
Description=AVScheduler Daemon
# Ensures networking is up, adjust if DB is remote or other dependencies exist
After=network.target

[Service]
# Type=simple assumes the ExecStart command remains in the foreground
Type=simple
# User/Group to run the service as. Ensure permissions on config, logs, db, pid file.
User=your_service_user
Group=your_service_group
# Set the working directory to the avscheduler project root
WorkingDirectory=/path/to/avscheduler
# Command to start the scheduler IN THE FOREGROUND. systemd handles daemonization.
# Ensure the python path is correct and the virtualenv is activated if needed,
# or use the absolute path to the python binary within the venv.
# Example using venv python:
# ExecStart=/path/to/avscheduler/venv/bin/python /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml start
# Example using system python (if dependencies installed globally):
ExecStart=/usr/bin/python3 /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml start
# Command to stop the scheduler using the CLI
ExecStop=/usr/bin/python3 /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml stop
# Command to reload configuration using the CLI (triggered by SIGHUP or systemctl reload)
ExecReload=/usr/bin/python3 /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml reload-config
# Restart the service if it fails
Restart=on-failure
RestartSec=5
# Optional: Set environment variables if needed
# Environment="FLASK_SECRET_KEY=your_production_secret"

# Ensure stdout/stderr are logged by systemd/journald
StandardOutput=journal
StandardError=journal

[Install]
# Start the service in the default multi-user runlevel
WantedBy=multi-user.target
```

**Important:**

  - Replace placeholders like `your_service_user`, `your_service_group`, and `/path/to/avscheduler`.
  - Ensure the specified `User` and `Group` have read access to the config file and write access to the database, log directory, and PID file directory.
  - Use absolute paths for `WorkingDirectory`, `ExecStart`, `ExecStop`, `ExecReload`, and the `--config` file path.
  - The `ExecStart` command **must** run the scheduler in the foreground (the default for `start` now). Systemd manages the background process.

### **Systemd Commands**

1.  **Create/Edit Service File**:
    ```bash
    sudo nano /etc/systemd/system/avscheduler.service
    ```
2.  **Reload Systemd**:
    ```bash
    sudo systemctl daemon-reload
    ```
3.  **Enable Service (Start on Boot)**:
    ```bash
    sudo systemctl enable avscheduler.service
    ```
4.  **Start Service Now**:
    ```bash
    sudo systemctl start avscheduler.service
    ```
5.  **Check Status**:
    ```bash
    sudo systemctl status avscheduler.service
    ```
6.  **View Logs (Journald)**:
    ```bash
    sudo journalctl -u avscheduler.service -f # Follow logs
    sudo journalctl -u avscheduler.service --since "1 hour ago" # View recent logs
    ```
7.  **Stop Service**:
    ```bash
    sudo systemctl stop avscheduler.service
    ```
8.  **Restart Service**:
    ```bash
    sudo systemctl restart avscheduler.service
    ```
9.  **Reload Configuration (using ExecReload)**:
    ```bash
    sudo systemctl reload avscheduler.service
    ```

-----

## **8. Database Schema (`core/database.py`)**

The scheduler uses SQLAlchemy to define the database schema.

### **Table: `job_execution_logs`**

| Column           | Type     | Description                              | Constraints/Indices                      |
| :--------------- | :------- | :--------------------------------------- | :--------------------------------------- |
| `id`             | INTEGER  | Auto-incrementing log ID.                | PRIMARY KEY                              |
| `job_id`         | STRING   | The ID of the job (from config).         | nullable=False, index                    |
| `exit_code`      | INTEGER  | The job's process exit code.             | nullable=False                           |
| `execution_time` | FLOAT    | Time taken to execute the job (seconds). | nullable=False                           |
| `timestamp`      | DATETIME | Time the log entry was created.          | nullable=False, index, default=now()     |
| `stdout`         | TEXT     | Captured standard output (optional).     | nullable=True                            |
| `stderr`         | TEXT     | Captured standard error (optional).      | nullable=True                            |

*(Indices on `job_id` and `timestamp` improve query performance for filtering and ordering.)*

-----

## **9. Contributing**

Contributions are welcome\! Please follow standard fork & pull request workflows. Report issues or suggest features via GitHub Issues on the repository.

-----

## **10. License**

This project is licensed under the MIT License. See the `LICENSE` file for details.
