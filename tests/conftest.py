import os

# The app reads its configuration at import time, so the test environment is
# set before any test module imports it.
os.environ.setdefault("UBERMENSCH_TOKEN", "test-token-test-token-test-token")
os.environ.setdefault("UBERMENSCH_PROVIDER", "echo")
os.environ.setdefault("UBERMENSCH_STATE", "/tmp/ubermensch-test-state")
