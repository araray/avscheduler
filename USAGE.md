### **How to use AVScheduler**

The AVScheduler provides **flexible job scheduling** and **dependency-based execution conditions**. Here's a deeper dive into these features to help you fully understand and use them effectively.

---

## **1. Schedule Types**

Jobs can be scheduled using one of the following types:

### **1.1. Cron-Based Scheduling**
This is a flexible, cron-style schedule using the `cron` syntax. You define exactly when a job should run using a string like `0 0 * * *` (run daily at midnight).

#### **Syntax**
```plaintext
* * * * *
- - - - -
| | | | +---- Day of the week (0 - 7, Sunday = 0 or 7)
| | | +------ Month (1 - 12)
| | +-------- Day of the month (1 - 31)
| +---------- Hour (0 - 23)
+------------ Minute (0 - 59)
```

#### **Examples**
- `0 * * * *`: Run at the start of every hour.
- `30 2 * * *`: Run at 2:30 AM every day.
- `0 0 1 * *`: Run at midnight on the first day of each month.

#### **Example Job in `config.toml`**
```toml
[jobs.job_1]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 0 * * *"  # Run daily at midnight
command = "print('Hello, World!')"
```

---

### **1.2. Interval-Based Scheduling**
Runs a job at regular intervals, defined in seconds, minutes, or hours.

#### **Example Configurations**
- **Every 30 minutes**:
  ```toml
  [jobs.job_2]
  type = "BASH"
  schedule_type = "interval"
  interval_seconds = 1800  # Run every 30 minutes
  command = "echo 'Job 2 running!'"
  ```
- **Every 2 hours**:
  ```toml
  [jobs.job_3]
  type = "PYTHON"
  schedule_type = "interval"
  interval_seconds = 7200  # Run every 2 hours
  command = "print('Running every 2 hours')"
  ```

---

### **1.3. Date-Based Scheduling**
Runs a job at a specific date and time.

#### **Example Configuration**
- **Run on a specific date**:
  ```toml
  [jobs.job_4]
  type = "PYTHON"
  schedule_type = "date"
  run_date = "2024-12-25 12:00:00"  # Run at noon on Christmas
  command = "print('Merry Christmas!')"
  ```

---

### **2. Job Conditions**

**Job Conditions** allow you to define dependencies between jobs. For example:
- Job A should only run if Job B was successful within the last 2 hours.
- Job A should only run if Job C has succeeded in its last 3 executions.

These conditions are evaluated dynamically at runtime by querying the execution logs stored in the SQLite database.

#### **Supported Conditions**

1. **`last_run_successful`**
   - Checks if the job completed successfully (exit code `0`) during its last run.

   Example:
   ```toml
   condition = "job_2.last_run_successful"
   ```

   - This means the current job will only run if `job_2`'s last execution succeeded.

2. **`finished_within(X)`**
   - Checks if the job finished successfully within the last `X` time.
   - Supported formats for `X`: `2h` (2 hours), `30m` (30 minutes), `10s` (10 seconds).

   Example:
   ```toml
   condition = "job_2.finished_within(2h)"
   ```

   - This means the current job will only run if `job_2` completed successfully within the past 2 hours.

3. **Logical Conditions**
   - Combine conditions using logical operators (`and`, `or`, `not`) to create more complex conditions.

   Example:
   ```toml
   condition = "job_2.last_run_successful and job_2.finished_within(1h)"
   ```

   - This means the current job will only run if:
     1. `job_2`'s last run was successful **and**
     2. `job_2` completed successfully within the past 1 hour.

---

#### **Example Job with Conditions**

```toml
[jobs.job_5]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 12 * * *"  # Run daily at noon
command = "print('Job 5 running!')"
condition = "job_2.last_run_successful and job_3.finished_within(30m)"
```

- `job_5` will only run if:
  1. `job_2` completed successfully during its last run **and**
  2. `job_3` finished successfully within the last 30 minutes.

---

#### **How Conditions are Evaluated**

The conditions are evaluated at runtime using the **execution logs** stored in the SQLite database (`job_execution_logs` table). This ensures dynamic dependency checks.

For example:
```python
def evaluate_condition(condition, job_id):
    # Parse and evaluate the condition using SQLite queries
    if "last_run_successful" in condition:
        # Query the logs for the last run of the referenced job
    if "finished_within" in condition:
        # Calculate timestamps and validate using SQL
```

---

### **3. Job Execution Workflow**

When a job is triggered (via a schedule or manual run):
1. **Condition Check**:
   - If a condition is defined for the job, the scheduler evaluates it.
   - If the condition fails, the job is skipped.
   - If no condition exists or the condition passes, the job proceeds to execution.

2. **Execution**:
   - The job's command is executed using its specified interpreter (e.g., Python, Bash).
   - The exit code, execution time, and timestamp are logged in the `job_execution_logs` table.

3. **Logging**:
   - Details of the job's execution (success/failure, time taken, etc.) are stored in the database and written to log files.

---

### **4. Interpreters**

Each job type (`PYTHON`, `BASH`, etc.) is mapped to a specific interpreter in the configuration file. For example:

```toml
[interpreters]
PYTHON = "/usr/bin/python3"
BASH = "/bin/bash"
```

#### **Supported Job Types**
- **PYTHON**:
  - Executes Python commands via the specified Python interpreter.
- **BASH**:
  - Executes shell commands.
- **JAVASCRIPT**:
  - Executes JavaScript commands using a specified Node.js executable.
- **Custom**:
  - Define your own interpreters for any language or binary.

---

### **5. Cleanup of Logs**

You can clean up old logs for specific jobs using either the **CLI** or the **Web UI**.

#### **CLI Command**
Use the `cleanup-logs` command:
```bash
python cli.py cleanup-logs job_id [--before "YYYY-MM-DD HH:MM:SS"] [--all]
```

- **`--before`**: Deletes logs older than the specified timestamp.
- **`--all`**: Deletes all logs for the given job.

Example:
```bash
python cli.py cleanup-logs job_1 --before "2024-12-01 00:00:00"
```

#### **Web UI**
- Navigate to the Job Details page (`/job/<job_id>`).
- Click the "Delete Logs" button to clean up logs for the selected job.

---

### **6. Examples**

#### **1. Daily Report Job with Dependencies**
```toml
[jobs.daily_report]
type = "PYTHON"
schedule_type = "cron"
schedule = "0 8 * * *"  # Run daily at 8:00 AM
command = "generate_report()"
condition = "data_etl_job.last_run_successful and data_etl_job.finished_within(1h)"
```

- This job will only run if `data_etl_job` succeeded within the past hour.

---

#### **2. Database Backup Job**
```toml
[jobs.backup_db]
type = "BASH"
schedule_type = "interval"
interval_seconds = 86400  # Run daily
command = "pg_dump -U postgres my_database > /backups/db_backup.sql"
```

---

#### **3. One-Time Migration Job**
```toml
[jobs.data_migration]
type = "PYTHON"
schedule_type = "date"
run_date = "2024-12-25 12:00:00"  # Run on a specific date
command = "run_migration_script()"
```
