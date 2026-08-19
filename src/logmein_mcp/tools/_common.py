from .._json import error_envelope

NO_TOKEN = error_envelope(
    "not_configured",
    "No LogMeIn Rescue credentials. Send the X-LogMeIn-Username and X-LogMeIn-Password headers.",
    False,
)
