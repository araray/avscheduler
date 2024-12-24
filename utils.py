"""
Utility functions for the AVScheduler project.
"""

import os
import toml


def get_valid_directory(env_var_name="AVSCHEDULER_DIR", fallback_toml_name=".avscheduler.toml", key_name="avscheduler_dir"):
    """
    Checks for a valid directory in the following order:
    1. An environment variable and its value as a directory.
    2. `$HOME/.something.toml` with a valid `something_dir` field.
    3. A `something.toml` file in the current directory with a valid `something_dir` field.

    Parameters:
    - env_var_name (str): Name of the environment variable to check.
    - fallback_toml_name (str): Name of the fallback TOML file to check (default: ".something.toml").
    - key_name (str): Key name in the TOML file that contains the directory path (default: "something_dir").

    Returns:
    - str: A valid directory path if found.
    - None: If no valid directory is found.
    """
    # Check if the environment variable exists and points to a valid directory
    env_var_value = os.getenv(env_var_name)
    if env_var_value and os.path.isdir(env_var_value):
        return env_var_value

    # Check if $HOME/.something.toml exists
    home = os.getenv("HOME")
    if home:
        home_toml_path = os.path.join(home, fallback_toml_name)
        if os.path.isfile(home_toml_path):
            try:
                # Parse the TOML file and check for the `something_dir` field
                with open(home_toml_path, "r") as file:
                    toml_data = toml.load(file)
                toml_dir = toml_data.get(key_name)
                if toml_dir and os.path.isdir(toml_dir):
                    return toml_dir
            except Exception as e:
                print(f"Error reading or parsing {home_toml_path}: {e}")

    # Check if `something.toml` exists in the current directory
    current_toml_path = os.path.join(os.getcwd(), fallback_toml_name.strip("."))
    if os.path.isfile(current_toml_path):
        try:
            # Parse the TOML file and check for the `something_dir` field
            with open(current_toml_path, "r") as file:
                toml_data = toml.load(file)
            toml_dir = toml_data.get(key_name)
            if toml_dir and os.path.isdir(toml_dir):
                return toml_dir
        except Exception as e:
            print(f"Error reading or parsing {current_toml_path}: {e}")

    # Return None if no valid directory is found
    return None