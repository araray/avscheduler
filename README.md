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
- **Python**: 3.8 or higher.
- **SQLite**: Default database for job logs (installed with Python).
- Recommended: A **virtual environment** for dependency isolation.

### **Step 1: Clone the Repository**
```bash
git clone https://github.com/araray/avscheduler.git
cd avscheduler
```

### **Step 2: Install Dependencies**
```bash
pip install -r requirements.txt
```

### **Step 3: Initialize the Database**
```bash
sqlite3 jobs.db < schema.sql
```

### **Step 4: Test Configuration**
Validate the `config.toml` file before starting:
```bash
python validate_config.py
```

---

## **3. Configuration**

All scheduler settings, job definitions, and interpreters are stored in a **TOML configuration file** (`config.toml`).

### **Example `config.toml`**

```toml
[settings]
db_path = "jobs.db"
pid_file = "/tmp/avscheduler.pid"

[web_server]
host = "127.0.0.1"
port = 8080

[interpreters]
PYTHON = "/usr/bin/python3"
BASH = "/bin/bash"

[jobs.job_1]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 * * * *"  # Every hour
command = "print('Hello from Job 1!')"
condition = "job_2.last_run_successful and job_2.finished_within(2h)"

[jobs.job_2]
type = "BASH"
schedule_type = "interval"
interval_seconds = 3600  # Every hour
command = "echo 'Running Job 2!'"
```

---

### **Configuration Options**

#### **[settings]**
| Key        | Description                                |
|------------|--------------------------------------------|
| `db_path`  | Path to the SQLite database file.          |
| `pid_file` | Path to store the daemon's PID file.       |

#### **[web_server]**
| Key     | Description                                   |
|---------|-----------------------------------------------|
| `host`  | IP address for the web interface.            |
| `port`  | Port for the web interface (e.g., `8080`).   |

#### **[interpreters]**
| Key      | Description                                    |
|----------|------------------------------------------------|
| `<type>` | Maps a job type to its interpreter's binary.   |

#### **[jobs]**
| Key              | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `type`           | Type of job (e.g., `PYTHON`, `BASH`). Must match an interpreter in `[interpreters]`. |
| `schedule_type`   | `cron`, `interval`, or `date`.                                              |
| `schedule`        | Cron schedule for `cron` jobs (e.g., `0 * * * *`).                         |
| `interval_seconds`| Interval in seconds for `interval` jobs.                                   |
| `run_date`        | Specific date/time for `date` jobs (e.g., `2024-12-25 12:00:00`).          |
| `command`         | Command to execute.                                                       |
| `condition`       | (Optional) Execution condition based on other jobs.                       |

---

## **4. Command Line Interface (CLI)**

The CLI allows you to manage the scheduler, jobs, and logs.

### **Run the CLI**
```bash
python cli.py [command]
```

### **Commands**

| Command         | Description                                  |
|------------------|----------------------------------------------|
| `start`         | Start the daemon (use `--daemonize` to run in the background). |
| `stop`          | Stop the daemon.                            |
| `status`        | Check the status of the daemon.             |
| `restart`       | Restart the daemon.                         |
| `list-jobs`     | List all jobs and their statuses.           |
| `run-job`       | Manually run a specific job.                |
| `add-job`       | Add a new job to the configuration.         |
| `edit-job`      | Edit an existing job in the configuration.  |
| `delete-job`    | Delete a job from the configuration.        |
| `view-logs`     | View execution logs for a specific job.     |
| `cleanup-logs`  | Delete old logs for a job.                  |
| `reload-config` | Reload the configuration file.              |

### **Examples**

1. **Start the Daemon**:
   ```bash
   python cli.py start --daemonize
   ```

2. **List All Jobs**:
   ```bash
   python cli.py list-jobs
   ```

3. **Run a Job Manually**:
   ```bash
   python cli.py run-job job_1
   ```

4. **Delete Logs**:
   ```bash
   python cli.py cleanup-logs job_2 --before "2024-12-01 00:00:00"
   ```

---

## **5. Web Interface**

### **Access the Web Interface**
Run the daemon:
```bash
python cli.py start --daemonize
```
Then navigate to:
```
http://127.0.0.1:8080
```

### **Main Screen**
- View all jobs with details:
  - Last execution time
  - Last exit code
  - Last execution duration
  - Next execution time
  - Condition
- View details of a specific job.

### **Job Details**

- View the full execution history of a job.
- Delete logs for a specific job.



### **Screenshots**



Main page:

![AVScheduler Main Screen](https://i.imgur.com/T1M11Dm.png)



Job details page:

![AVScheduler Job Details Page](https://i.imgur.com/2VpmTAx.png)

---

## **6. System Integration (Systemd)**

Integrate the scheduler with **systemd** for automatic startup and process management.

### **Service File**
Create a systemd service file (`/etc/systemd/system/avscheduler.service`):

```ini
[Unit]
Description=Python AVScheduler Daemon
After=network.target

[Service]
Type=simple
User=<your_user>
Group=<your_usergroup>
WorkingDirectory=/path/to/avscheduler
ExecStart=/usr/bin/python3 /path/to/avscheduler/cli.py start --daemonize
ExecStop=/usr/bin/python3 /path/to/avscheduler/cli.py stop
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### **Commands**
- Reload systemd:
  ```bash
  sudo systemctl daemon-reload
  ```
- Enable the service:
  ```bash
  sudo systemctl enable avscheduler.service
  ```
- Start the service:
  ```bash
  sudo systemctl start avscheduler.service
  ```
- Check status:
  ```bash
  sudo systemctl status avscheduler.service
  ```

---

## **7. Database Schema**

### **Table: `job_execution_logs`**
| Column           | Type    | Description                              |
|-------------------|---------|------------------------------------------|
| `id`             | INTEGER | Auto-incrementing log ID.                |
| `job_id`         | TEXT    | The ID of the job.                       |
| `exit_code`      | INTEGER | The job's exit code (0 for success).     |
| `execution_time` | REAL    | Time taken to execute the job (seconds). |
| `timestamp`      | TEXT    | The time the job was executed.           |

---

## **8. Examples**

### **Example Jobs**

1. **Hourly Job with Dependencies**
```toml
[jobs.job_1]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 * * * *"
command = "print('Job 1 running')"
condition = "job_2.last_run_successful and job_2.finished_within(2h)"
```

2. **Daily Backup**
```toml
[jobs.daily_backup]
type = "BASH"
schedule_type = "interval"
interval_seconds = 86400  # 24 hours
command = "tar -czf /backups/daily_backup.tar.gz /important/data"
```

---

## **9. Contributing**

Contributions are welcome! Feel free to submit issues, feature requests, or pull requests on the [GitHub repository](https://github.com/araray/avscheduler).

---

## **10. License**

This project is licensed under the MIT License. See the `LICENSE` file for details.

