"""Domain exceptions used by the Replay workflow."""


class LabmateError(Exception):
    """Base class for user-facing workflow errors."""


class InputValidationError(LabmateError):
    """Raised when CDR or antigen input fails validation."""


class FixtureIntegrityError(LabmateError):
    """Raised when a Replay fixture or its input hashes do not match."""


class StateTransitionError(LabmateError):
    """Raised for an invalid workflow stage transition."""


class LiveCapabilityUnavailable(LabmateError):
    """Raised when code attempts to invoke a deliberately disabled Live path."""

