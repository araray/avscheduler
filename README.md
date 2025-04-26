# **AVScheduler Tool**

A Python-based job scheduler designed to dynamically manage, execute, and monitor scheduled tasks with dependency-based execution, detailed logging, and a powerful web interface and CLI.

---

## **Table of Contents**
1. [Features](#features)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Command Line Interface (CLI)](#command-line-interface-cli)
5. [Web Interface](#web-interface)
6. [System Integration (Systemd)](#system-integration-systemd)
7. [Database Schema](#database-schema)
8. [Examples](#examples)
9. [Contributing](#contributing)
10. [License](#license)

---

## **1. Features**

- **Flexible Scheduling**:
  - Supports **cron-like schedules**, **interval-based scheduling**, and **date-based triggers**.
  - Define jobs with dependencies to execute only when conditions are met.

- **Dependency Management**:
  - Jobs can have conditions such as:
    - `job_2.last_run_successful`
    - `job_3.finished_within(2h)`

- **Dynamic Management**:
  - Use the **CLI** or **Web Interface** to add, edit, delete, or manually run jobs dynamically without restarting the daemon.

- **Powerful Logging**:
  - Logs every job execution, including:
    - **Timestamps**
    - **Execution time**
    - **Exit code**
    - **Stdout/Stderr** (optional)
  - Cleanup old logs via the CLI or Web Interface.

- **Web Interface**:
  - View job statuses and execution history.
  - Manage logs and dynamically inspect jobs.

- **CLI**:
  - Fully-featured CLI for daemon management, job execution, and configuration.

- **Systemd Integration**:
  - Easily run the scheduler as a background service with automatic startup.

---

## **2. Installation**

### **Prerequisites**
- **Python**: 3.11 or higher (check `requirements.txt` for specific library versions).
- **SQLite**: Default database for job logs (installed with Python).
- Recommended: A **virtual environment** for dependency isolation.

### **Step 1: Clone the Repository**
```bash
git clone [https://github.com/araray/avscheduler.git](https://github.com/araray/avscheduler.git)
cd avscheduler
```

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
While SQLAlchemy creates tables automatically, you might want to ensure the DB file exists initially.
```bash
# This step might not be strictly necessary if using SQLAlchemy's create_all
# touch /path/to/your/jobs.db # Ensure the file exists if needed by init_db permissions
```

---

## **3. Configuration**

All scheduler settings, job definitions, and interpreters are stored in a **TOML configuration file** (`config.toml`).

### **Example `config.toml`**

```toml
[settings]
# Path to the SQLite database file. Ensure directory exists.
db_path = "/var/lib/avscheduler/jobs.db"
# Path to store the daemon's PID file. Ensure directory exists.
pid_file = "/var/run/avscheduler/avscheduler.pid"

[web_server]
host = "127.0.0.1"
port = 5000 # Default Flask port

[interpreters]
PYTHON = "/usr/bin/python3" # Or path from `which python3`
BASH = "/bin/bash"

[jobs.job_1]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 * * * *"  # Every hour at minute 0
command = "print('Hello from Job 1!')"
condition = "job_2.last_run_successful and job_2.finished_within(2h)"
# Optional: Timeout in seconds for this job
# timeout_seconds = 300
# Optional: Path to a file with environment variables
# env_file = "/path/to/job1.env"


[jobs.job_2]
type = "BASH"
schedule_type = "interval"
interval_seconds = 3600  # Every hour
command = "echo 'Running Job 2! Exit code 0.'"

[jobs.failing_job]
type = "BASH"
schedule_type = "interval"
interval_seconds = 1800 # Every 30 mins
command = "echo 'This job will fail'; exit 1"
```

---

### **Configuration Options**

#### **[settings]**
| Key        | Description                                                    | Default (if not set) |
|------------|----------------------------------------------------------------|----------------------|
| `db_path`  | Path to the SQLite database file. **Directory must exist.** | `./jobs.db`          |
| `pid_file` | Path to store the daemon's PID file. **Directory must exist.** | `./logs/avscheduler.pid` |

#### **[web_server]**
| Key     | Description                               | Default |
|---------|-------------------------------------------|---------|
| `host`  | IP address for the web interface.         | `127.0.0.1` |
| `port`  | Port for the web interface (e.g., `5000`).| `5000`    |

#### **[interpreters]**
| Key      | Description                                    |
|----------|------------------------------------------------|
| `<type>` | Maps a job type (e.g., `PYTHON`) to its interpreter's absolute binary path. |

#### **[jobs.<job_id>]**
| Key                 | Description                                                                 | Required? |
|---------------------|-----------------------------------------------------------------------------|-----------|
| `type`              | Type of job (e.g., `PYTHON`, `BASH`). Must match a key in `[interpreters]`. | Yes       |
| `schedule_type`     | `cron`, `interval`, or `date`.                                              | Yes       |
| `command`           | Command string to execute.                                                  | Yes       |
| `schedule`          | Cron schedule string for `cron` jobs (e.g., `0 * * * *`).                  | If `schedule_type` is `cron` |
| `interval_seconds`  | Interval in seconds for `interval` jobs.                                   | If `schedule_type` is `interval` |
| `run_date`          | Specific date/time for `date` jobs (ISO format: `YYYY-MM-DD HH:MM:SS`).    | If `schedule_type` is `date` |
| `condition`         | (Optional) Execution condition based on other jobs' status.                 | No        |
| `env_file`          | (Optional) Path to a `.env` file to load environment variables from.        | No        |
| `timeout_seconds`   | (Optional) Maximum execution time in seconds before the job is terminated.  | No        |
| `name`              | (Optional) Display name for the job (defaults to `job_id`).                 | No        |
| `misfire_grace_time`| (Optional) Seconds after the scheduled run time that the job is allowed to start. | No (APScheduler default) |
| `coalesce`          | (Optional) Run missed executions only once (`true`) or for every missed run (`false`). | No (APScheduler default: `true`) |
| `max_instances`     | (Optional) Maximum number of concurrent instances of the job.              | No (APScheduler default: `1`) |


---

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
|-----------------|--------------------------------------------------------------------------------|
| `start`         | Start the scheduler process in the foreground (use `--foreground` explicitly). **For background execution, use a process manager like systemd.** |
| `stop`          | Stop the running scheduler daemon process (using the PID file).                |
| `status`        | Check the status of the scheduler daemon (using the PID file).                 |
| `restart`       | Stop and then start the scheduler daemon (runs foreground after restart).      |
| `reload-config` | Signal the running daemon to reload the configuration file (sends `SIGHUP`).   |

### **Job & Log Commands**

| Command         | Description                                                              |
|-----------------|--------------------------------------------------------------------------|
| `list-jobs`     | List all jobs defined in the configuration and their last log status.    |
| `run-job`       | Manually run a specific job by its ID, bypassing schedule and conditions. |
| `add-job`       | Add a new job definition to the configuration file.                      |
| `edit-job`      | Edit properties of an existing job in the configuration file.            |
| `delete-job`    | Delete a job definition from the configuration file.                     |
| `view-logs`     | View job execution logs from the database.                               |
| `cleanup-logs`  | Delete execution logs for a specific job.                                |

**Note:** `add-job`, `edit-job`, `delete-job` modify the `config.toml` file. You need to run `reload-config` or `restart` the daemon for these changes to take effect in the running scheduler.

### **Examples**

1.  **Start the Scheduler (Foreground)**:
    ```bash
    python cli.py --config /path/to/your/config.toml start --foreground
    ```
    *(For background, see Systemd section)*

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

5.  **View Logs for a Specific Job**:
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

---

## **5. Web Interface**

The web interface provides a dashboard to monitor job status and view execution logs.

### **Access the Web Interface**

1.  Start the scheduler daemon (e.g., using `systemd` or `python cli.py start --foreground`).
2.  Ensure the `host` and `port` in the `[web_server]` section of your `config.toml` are correctly set.
3.  Navigate your browser to `http://<host>:<port>` (e.g., `http://127.0.0.1:5000`).

### **Features**

-   **Dashboard (`/`)**:
    -   View all jobs listed in the configuration.
    -   See the last execution timestamp, exit code, and duration from the logs.
    -   View the configured schedule and condition.
    -   (Future Work) Display the next scheduled run time (requires communication with the running scheduler).
-   **Job Details (`/job/<job_id>`)**:
    -   View the configuration details for the specific job.
    -   See a table of recent execution logs (timestamp, exit code, duration, output snippet).
    -   Button to delete all logs for that specific job (requires confirmation).

*(Screenshots need updating after Phase 2/3)*

---

## **6. System Integration (Systemd)**

Integrate the scheduler with **systemd** for robust background execution, automatic startup, and process management.

### **Service File (`/etc/systemd/system/avscheduler.service`)**

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
# ExecStart=/path/to/avscheduler/venv/bin/python /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml start --foreground
# Example using system python (if dependencies installed globally):
ExecStart=/usr/bin/python3 /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml start --foreground
# Command to stop the scheduler using the CLI
ExecStop=/usr/bin/python3 /path/to/avscheduler/cli.py --config /path/to/avscheduler/config.toml stop
# Restart the service if it fails
Restart=on-failure
RestartSec=5
# Optional: Set environment variables if needed
# Environment="FLASK_SECRET_KEY=your_production_secret"
# Environment="AVSCHEDULER_DIR=/path/to/avscheduler" # If using utils.get_valid_directory

# Ensure stdout/stderr are logged by systemd/journald
StandardOutput=journal
StandardError=journal

[Install]
# Start the service in the default multi-user runlevel
WantedBy=multi-user.target
```

**Important:**
* Replace placeholders like `your_service_user`, `your_service_group`, and `/path/to/avscheduler`.
* Ensure the specified `User` and `Group` have read access to the config file and write access to the database, log directory, and PID file directory.
* Use absolute paths for `WorkingDirectory`, `ExecStart`, `ExecStop`, and the `--config` file path.
* The `ExecStart` command **must** run the scheduler in the foreground (`--foreground` flag) because `Type=simple` expects this. Systemd manages the background process.

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

---

## **7. Database Schema (`core/database.py`)**

The scheduler uses SQLAlchemy to define the database schema.

### **Table: `job_execution_logs`**
| Column           | Type      | Description                              | Constraints/Indices |
|------------------|-----------|------------------------------------------|---------------------|
| `id`             | INTEGER   | Auto-incrementing log ID.                | PRIMARY KEY         |
| `job_id`         | STRING    | The ID of the job (from config).         | nullable=False, index |
| `exit_code`      | INTEGER   | The job's process exit code.             | nullable=False      |
| `execution_time` | FLOAT     | Time taken to execute the job (seconds). | nullable=False      |
| `timestamp`      | DATETIME  | Time the log entry was created.          | nullable=False, index, default=now |
| `stdout`         | TEXT      | Captured standard output (optional).     | nullable=True       |
| `stderr`         | TEXT      | Captured standard error (optional).      | nullable=True       |

*(Indices on `job_id` and `timestamp` improve query performance for filtering and ordering.)*

---

## **8. Examples**

*(See `config.example.toml` and `USAGE.md` for more detailed examples)*

### **Example Job: Hourly Report with Dependency**
```toml
# In config.toml
[jobs.generate_report]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 * * * *" # Run hourly at minute 0
command = "/path/to/scripts/report_generator.py --output /data/reports/hourly.csv"
# Only run if the data aggregation job succeeded in the last 90 minutes
condition = "aggregate_data.last_run_successful and aggregate_data.finished_within(90m)"

[jobs.aggregate_data]
type = "BASH"
schedule_type = "cron"
schedule = "*/15 * * * *" # Run every 15 minutes
command = "/path/to/scripts/aggregate_data.sh"
timeout_seconds = 600 # Allow 10 minutes for aggregation
```

---

## **9. Contributing**

Contributions are welcome! Please follow standard fork & pull request workflows. Report issues or suggest features via GitHub Issues on the [repository](https://github.com/araray/avscheduler).

---

## **10. License**

This project is licensed under the MIT License. See the `LICENSE` file for details.
