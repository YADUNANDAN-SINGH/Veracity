# The same suite, the same results, inside the judge image or on a laptop: what the
# image's ENV or someone's .env sets must not change what the tests see. Runs before
# any app module is imported, and those read these variables at import time.

import os

for name in (
    "VERA_MODE", "VERA_UPLOAD", "VERA_REGION", "VERA_LANGUAGE", "VERA_WHISPER_MODEL", "VERA_STATIC_DIR", "VERA_DB",
    "VERA_PAYPAL_STANDIN", "VERA_FAKE", "VERA_SANDBOX_BUYER_EMAIL",
    "VERA_SANDBOX_BUYER_PASSWORD", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "PAYPAL_PAYOUTS",
):
    os.environ.pop(name, None)
