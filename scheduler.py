# scheduler.py

"""
Main entry point for starting the AVScheduler daemon process.
Loads configuration and delegates to the core scheduler logic.
"""

import os
import sys
import argparse
import logging

# Adjust path to import from core and utils if necessary
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    from core.scheduler_logic import load_config, start_scheduler_process, logger, read_pid, is_process_running, remove_pid
    from utils import get_valid_directory # Assuming utils.py is still relevant
except ImportError as e:
    print(f"Error importing core modules: {e}", file=sys.stderr)
    print("Ensure the project structure is correct and PYTHONPATH is set if needed.", file=sys.stderr)
    sys.exit(1)

# Determine the default config file path relative to this script or project root
# Use get_valid_directory to find the base path if needed
try:
    base_dir = get_valid_directory()
    if base_dir:
        DEFAULT_CONFIG_FILE = os.path.join(base_dir, "config.toml")
    else:
        # Fallback if get_valid_directory fails
        DEFAULT_CONFIG_FILE = os.path.join(project_root, "config.toml")
except Exception as e:
    print(f"Error determining default config path: {e}", file=sys.stderr)
    # Fallback to a simple relative path
    DEFAULT_CONFIG_FILE = os.path.join(project_root, "config.toml")


def main():
    """
    Parses command-line arguments and starts the scheduler daemon.
    """
    parser = argparse.ArgumentParser(description="AVScheduler Daemon Runner")
    parser.add_argument(
        "--config", "-c",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to the configuration file (default: {DEFAULT_CONFIG_FILE})"
    )
    # Add other daemon-specific arguments if needed (e.g., --foreground)
    # The --daemonize flag is handled by the service manager (systemd) or process runner (like nohup)
    # The core logic assumes it's running *as* the daemon process.

    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config)

        # Start the main scheduler process logic
        logger.info("Starting AVScheduler daemon...")
        start_scheduler_process(config) # This function now handles the main loop and PID management

    except FileNotFoundError:
        logger.critical(f"Configuration file not found: {args.config}")
        sys.exit(1)
    except Exception as e:
        # Catch any other unexpected errors during startup
        logger.critical(f"Failed to start scheduler daemon: {e}", exc_info=True)
        # Attempt cleanup if PID file was created by load_config/start_scheduler_process
        try:
            pid_file = config.get("settings", {}).get("pid_file")
            if pid_file and os.path.exists(pid_file):
                 current_pid = read_pid(pid_file)
                 if current_pid == os.getpid(): # Only remove if it's our PID
                     remove_pid(pid_file)
        except Exception as cleanup_e:
             logger.error(f"Error during cleanup after startup failure: {cleanup_e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
