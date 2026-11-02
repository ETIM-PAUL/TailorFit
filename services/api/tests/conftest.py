import os

# Tests must never call the live Meta API, even when a developer's .env has a key.
os.environ["TAILORFIT_STUBS"] = "1"

# ...and never touch the real order database or photo folder.
import tempfile

_tmp = tempfile.mkdtemp(prefix="tailorfit-tests-")
os.environ.setdefault("TAILORFIT_DB", os.path.join(_tmp, "tests.db"))
os.environ.setdefault("TAILORFIT_PHOTOS", os.path.join(_tmp, "photos"))
