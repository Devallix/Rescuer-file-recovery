from .__init__ import APP_DESCRIPTION, APP_DEVELOPER, APP_ID, APP_NAME, APP_TAGLINE, __version__

ORG_NAME = "Rescuer"
SINGLE_INSTANCE_ID = APP_ID + ".single-instance"

DB_FILENAME = "rescuer.db"
LOG_FILENAME = "rescuer.log"
CONFIG_FILENAME = "settings.json"
SIGNATURES_FILENAME = "signatures.json"

DEFAULT_THEME = "dark"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MIN_SCAN_BATCH_SIZE = 500
MAX_PROGRESS_EVENTS_PER_SECOND = 10
