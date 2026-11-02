import os

# Tests must never call the live Meta API, even when a developer's .env has a key.
os.environ["TAILORFIT_STUBS"] = "1"
