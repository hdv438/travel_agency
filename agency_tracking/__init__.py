__version__ = "0.0.1"

# clearance_engine registers itself into state_machine.TRANSITION_SIDE_EFFECTS as an import
# side effect (Step 7) — importing it here guarantees that registration has happened before
# any transition() call, regardless of which submodule triggered the app's first import.
# Deliberately at the bottom: if this ever needs a second such module, this becomes the one
# place all of them get imported from, not scattered import-order assumptions elsewhere.
import agency_tracking.clearance_engine  # noqa: E402,F401
import agency_tracking.finance_engine  # noqa: E402,F401
import agency_tracking.api_docs  # noqa: E402,F401
