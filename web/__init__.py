# web/__init__.py

"""
Initializes the Flask application and registers blueprints.
Uses the Application Factory pattern.
"""

import os
import logging
from flask import Flask, g
from apscheduler.schedulers.background import BackgroundScheduler # Import scheduler type
from typing import Dict, Any

# Import core components needed by web routes
try:
    # DB access is needed
    from core.database import init_db as core_init_db, get_session as core_get_session
    # Config loader might be needed if web needs to reload config independently (unlikely)
    # from core.config_loader import load_config as core_load_config
except ImportError as e:
    logging.critical(f"Failed to import core modules in web/__init__.py: {e}", exc_info=True)
    raise

def create_app(scheduler_config: Dict[str, Any], scheduler_instance: BackgroundScheduler) -> Flask:
    """
    Application factory function.

    Args:
        scheduler_config: The pre-loaded configuration dictionary.
        scheduler_instance: The running APScheduler instance.

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__,
                template_folder='../templates', # Point to templates dir outside 'web'
                static_folder='../static'       # Point to static dir outside 'web'
                )

    # --- Use Provided Configuration ---
    app.config['SCHEDULER_CONFIG'] = scheduler_config
    app.config['SCHEDULER_INSTANCE'] = scheduler_instance # Store scheduler instance
    db_path = scheduler_config.get('settings', {}).get('db_path')

    if not db_path:
         logging.error("Database path ('db_path') not found in provided config. Web UI database access will fail.")
         app.config['DB_PATH'] = None # Indicate DB path is missing
    else:
        app.config['DB_PATH'] = db_path
        try:
            # Initialize DB access for the web app process/thread
            # This assumes the DB file itself is already created/managed by the main process
            core_init_db(db_path)
            logging.info(f"Web UI database session factory configured for: {db_path}")
        except Exception as e:
            logging.error(f"Web UI failed to initialize database access for '{db_path}': {e}", exc_info=True)
            app.config['DB_PATH'] = None # Mark DB as unavailable

    # --- Configure Flask App Settings ---
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_change_me')
    # Add other Flask configurations as needed

    # --- Database Session Management (per request) ---
    @app.before_request
    def before_request():
        """Opens a database session for the request."""
        g.config = app.config.get('SCHEDULER_CONFIG', {}) # Get config from app context
        g.scheduler = app.config.get('SCHEDULER_INSTANCE') # Get scheduler from app context
        if app.config.get('DB_PATH'): # Only try to get session if DB path was valid
            try:
                g.db_session = core_get_session()
            except RuntimeError as e:
                logging.error(f"Failed to get DB session for request: {e}")
                g.db_session = None
        else:
            g.db_session = None # DB not available


    @app.teardown_request
    def teardown_request(exception=None):
        """Closes the database session after the request."""
        session = g.pop('db_session', None)
        if session is not None:
            session.close()
        if exception:
             logging.error(f"Exception during request teardown: {exception}", exc_info=exception)


    # --- Register Blueprints ---
    try:
        from . import routes # Import routes after app is created
        app.register_blueprint(routes.bp)
        logging.info("Registered 'routes' blueprint.")
        # Register other blueprints here
    except ImportError as e:
         logging.error(f"Failed to import or register blueprints: {e}", exc_info=True)


    logging.info("Flask application created successfully for Web UI.")
    return app
