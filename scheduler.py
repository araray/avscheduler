# scheduler.py

"""
Main entry point for starting the AVScheduler daemon process.
Loads configuration, initializes DB, starts Web UI thread, and starts scheduler logic.
"""

import os
import sys
import argparse
import logging
from threading import Thread

# Adjust path to import from core and utils if necessary
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    from core.config_loader import load_config
    from core.scheduler_logic import start_scheduler_process, scheduler as global_scheduler, logger
    from core.database import init_db as core_init_db
    from utils import get_valid_directory
    # Import create_app safely
    try:
        from web import create_app
    except ImportError as e:
        logging.warning(f"Could not import Flask app factory (web.create_app): {e}. Web UI will not start.")
        create_app = None
except ImportError as e:
    print(f"Error importing core modules: {e}", file=sys.stderr)
    print("Ensure the project structure is correct and PYTHONPATH is set if needed.", file=sys.stderr)
    sys.exit(1)

# Default config path resolution
try:
    base_dir = get_valid_directory()
    DEFAULT_CONFIG_FILE = os.path.join(base_dir or project_root, "config.toml")
except Exception as e:
    print(f"Error determining default config path: {e}", file=sys.stderr)
    DEFAULT_CONFIG_FILE = os.path.join(project_root, "config.toml")

def start_web_ui_in_thread(config: dict, scheduler_instance):
    """Starts the Flask app in a daemon thread."""
    if create_app is None:
        logger.warning("Flask app factory not available. Cannot start web UI.")
        return None

    web_host = config.get("web_server", {}).get("host", "127.0.0.1")
    web_port = config.get("web_server", {}).get("port", 5000)

    def run_flask():
        try:
            # Create app using the factory, passing config and scheduler instance
            flask_app = create_app(scheduler_config=config, scheduler_instance=scheduler_instance)
            logger.info(f"Starting Flask web server on http://{web_host}:{web_port}...")
            flask_app.run(host=web_host, port=web_port, debug=False, use_reloader=False)
            logger.info("Flask web server thread finished.")
        except Exception as e:
            logger.error(f"Flask web server thread failed: {e}", exc_info=True)

    flask_thread = Thread(target=run_flask, daemon=True, name="FlaskWebServerThread")
    flask_thread.start()
    logger.info("Flask web server thread started.")
    return flask_thread

def main():
    """
    Parses arguments, loads config, starts DB, Web UI, and Scheduler.
    """
    parser = argparse.ArgumentParser(description="AVScheduler Daemon Runner")
    parser.add_argument(
        "--config", "-c",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to the configuration file (default: {DEFAULT_CONFIG_FILE})"
    )
    args = parser.parse_args()

    config = None # Define config here to allow access in except block
    try:
        # 1. Load Configuration
        config = load_config(args.config)
        db_path = config.get("settings", {}).get("db_path")
        if not db_path:
             logger.critical("DB path not found in configuration. Exiting.")
             sys.exit(1)

        # 2. Initialize Database
        logger.info(f"Initializing database: {db_path}")
        core_init_db(db_path)

        # 3. Start Web UI Thread
        logger.info("Attempting to start Web UI thread...")
        web_thread = start_web_ui_in_thread(config, global_scheduler)
        if web_thread:
             logger.info("Web UI thread initiated.")
        else:
             logger.warning("Web UI thread could not be started.")

        # 4. Start the main scheduler process logic (blocking)
        logger.info("Starting AVScheduler core process...")
        # Pass the already loaded config
        start_scheduler_process(config)

    except FileNotFoundError:
        logger.critical(f"Configuration file not found: {args.config}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Failed to start scheduler daemon: {e}", exc_info=True)
        # Attempt cleanup if PID file was created by start_scheduler_process
        try:
            if config: # Check if config was loaded before error
                 pid_file = config.get("settings", {}).get("pid_file")
                 if pid_file and os.path.exists(pid_file):
                      from core.scheduler_logic import read_pid, remove_pid # Import here for cleanup
                      current_pid = read_pid(pid_file)
                      if current_pid == os.getpid():
                           remove_pid(pid_file)
        except Exception as cleanup_e:
             logger.error(f"Error during cleanup after startup failure: {cleanup_e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
