# core/config_loader.py

"""
Handles loading and validation of the TOML configuration file.
"""

import os
import toml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Determine project root and logs directory relative to this file's location
# Assumes core/ is one level down from project root
project_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logs_dir = os.path.join(project_root_dir, "logs")

def load_config(config_file: str) -> Dict[str, Any]:
    """
    Loads the TOML configuration file, validates essential sections,
    and sets defaults for missing optional keys.

    Args:
        config_file: Path to the configuration file.

    Returns:
        A dictionary containing the loaded configuration.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        toml.TomlDecodeError: If the config file is invalid TOML.
        ValueError: If essential sections/keys are missing or invalid.
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file '{config_file}' not found.")

    logger.info(f"Loading configuration from: {config_file}")
    try:
        config = toml.load(config_file)
        # Store the path from where the config was loaded for potential use later (e.g., reload)
        config["_config_file_path"] = config_file
    except toml.TomlDecodeError as e:
        logger.error(f"Error decoding TOML configuration file '{config_file}': {e}")
        raise

    # --- Configuration Validation and Defaults ---
    if "settings" not in config:
        logger.warning("Config missing [settings] section, using defaults.")
        config["settings"] = {}
    if "db_path" not in config["settings"]:
        # Default DB path relative to config file's directory or project root
        default_db_path = os.path.join(os.path.dirname(config_file) or '.', "jobs.db")
        config["settings"]["db_path"] = default_db_path
        logger.info(f"Config missing 'db_path', defaulting to: {default_db_path}")
    if "pid_file" not in config["settings"]:
        # Default PID path relative to project root's logs dir
        default_pid_path = os.path.join(logs_dir, "avscheduler.pid")
        config["settings"]["pid_file"] = default_pid_path
        logger.info(f"Config missing 'pid_file', defaulting to: {default_pid_path}")

    # Ensure essential settings exist after defaults
    if not config["settings"].get("db_path"):
         raise ValueError("Missing required setting 'db_path' in [settings]")
    if not config["settings"].get("pid_file"):
         raise ValueError("Missing required setting 'pid_file' in [settings]")


    if "interpreters" not in config:
        logger.warning("Config missing [interpreters] section. Jobs might fail.")
        config["interpreters"] = {}

    if "jobs" not in config:
        logger.warning("Config missing [jobs] section. No jobs to schedule.")
        config["jobs"] = {}

    if "web_server" not in config:
        logger.warning("Config missing [web_server] section, using defaults.")
        config["web_server"] = {}
    if "host" not in config["web_server"]:
        config["web_server"]["host"] = "127.0.0.1"
        logger.info("Config missing 'web_server.host', defaulting to: 127.0.0.1")
    if "port" not in config["web_server"]:
        config["web_server"]["port"] = 5000 # Default Flask port
        logger.info("Config missing 'web_server.port', defaulting to: 5000")

    logger.info("Configuration loaded and validated successfully.")
    return config
