# web/__init__.py

"""
Initializes the Flask application and registers blueprints.
Uses the Application Factory pattern.
"""

import os
import logging
from flask import Flask, g
from apscheduler.schedulers.background import BackgroundScheduler # Import scheduler type

# Import core components needed by web routes
try:
    # Assuming config loading is needed globally or passed during creation
    from core.scheduler_logic import load_config as core_load_config
    from core.database import init_db as core_init_db, get_session as core_get_session
    # Import the global scheduler instance if web needs direct access (use carefully)
    # It's often better to interact via functions/API if possible
    from core.scheduler_logic import scheduler as global_scheduler
except ImportError as e:
    # Handle potential import errors if structure is wrong
    logging.critical(f"Failed to import core modules in web/__init__.py: {e}", exc_info=True)
    raise # Re-raise to prevent app from starting incorrectly

def create_app(config_path: str = None) -> Flask:
    """
    Application factory function.

    Args:
        config_path: Optional path to the configuration file. If None,
                     it tries to find a default config.toml.

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__,
                template_folder='../templates', # Point to templates dir outside 'web'
                static_folder='../static'       # Point to static dir outside 'web'
                )

    # --- Configuration Loading ---
    if config_path is None:
        # Determine default config path relative to the instance folder or project root
        # This might need adjustment based on how the app is run
        default_config = os.path.join(app.instance_path, '..', 'config.toml')
        config_path = default_config
        # Log which config file is being attempted
        logging.info(f"No config_path provided, attempting default: {config_path}")


    if not os.path.exists(config_path):
         logging.error(f"Configuration file not found at resolved path: {config_path}. Web UI might not function correctly.")
         # Decide whether to raise an error or proceed with defaults/empty config
         app.config['SCHEDULER_CONFIG'] = {} # Use empty config
         app.config['DB_PATH'] = 'default_web_jobs.db' # Default DB path for web if config fails
         app.config['SCHEDULER_INSTANCE'] = None # No scheduler if config fails
    else:
        try:
            # Load the main scheduler configuration using the core function
            scheduler_config = core_load_config(config_path)
            app.config['SCHEDULER_CONFIG'] = scheduler_config
            app.config['DB_PATH'] = scheduler_config.get('settings', {}).get('db_path', 'jobs.db')
            # Make the global scheduler instance accessible via app context
            # Note: This assumes the scheduler is already running or will be started
            # by a separate process (the daemon). The web UI interacts with it.
            app.config['SCHEDULER_INSTANCE'] = global_scheduler
            logging.info(f"Loaded scheduler config into Flask app from: {config_path}")

            # Initialize DB using the path from the loaded config *if* the web app needs to
            # Typically, the daemon initializes the DB. Web might only need read access.
            # If web modifies DB directly (e.g., deleting logs), it needs init_db.
            # Consider potential issues if daemon and web init DB separately.
            # Let's assume web needs it for log deletion for now.
            core_init_db(app.config['DB_PATH'])

        except Exception as e:
            logging.critical(f"Failed to load configuration '{config_path}' or init DB for Flask app: {e}", exc_info=True)
            # Handle error appropriately - maybe raise it or set defaults
            app.config['SCHEDULER_CONFIG'] = {}
            app.config['DB_PATH'] = 'error_web_jobs.db'
            app.config['SCHEDULER_INSTANCE'] = None


    # --- Configure Flask App Settings ---
    # Example: Secret key for sessions, CSRF protection (needed for Flask-WTF)
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_change_me')
    # Add other Flask configurations as needed

    # --- Database Session Management (per request) ---
    @app.before_request
    def before_request():
        """Opens a database session for the request."""
        try:
            g.db_session = core_get_session()
            # Make scheduler instance easily available in request context
            g.scheduler = app.config.get('SCHEDULER_INSTANCE')
            g.config = app.config.get('SCHEDULER_CONFIG')
        except RuntimeError as e:
            # Handle case where DB wasn't initialized
             logging.error(f"Failed to get DB session for request: {e}")
             g.db_session = None
             g.scheduler = None
             g.config = {}


    @app.teardown_request
    def teardown_request(exception=None):
        """Closes the database session after the request."""
        session = g.pop('db_session', None)
        if session is not None:
            session.close()
        # Log exceptions passed during teardown
        if exception:
             logging.error(f"Exception during request teardown: {exception}", exc_info=exception)


    # --- Register Blueprints ---
    try:
        from . import routes # Import routes after app is created to avoid circular imports
        app.register_blueprint(routes.bp)
        logging.info("Registered 'routes' blueprint.")
        # Register other blueprints here (e.g., for job management later)
        # from . import jobs
        # app.register_blueprint(jobs.bp, url_prefix='/jobs')

    except ImportError as e:
         logging.error(f"Failed to import or register blueprints: {e}", exc_info=True)


    # --- Basic Root Route (Optional - can be in blueprint) ---
    # @app.route('/hello')
    # def hello():
    #     return 'Hello from AVScheduler Web!'

    logging.info("Flask application created successfully.")
    return app
