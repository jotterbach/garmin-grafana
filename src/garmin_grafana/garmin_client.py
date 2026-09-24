"""
Garmin Connect login, extracted from garmin_fetch.py's former garmin_login().

Also fixes the headless-MFA crash that shipped in upstream commit 6720ed9:
_prompt_mfa() used to be an inline `lambda: input(...)`, which raises a bare
EOFError with no useful message when stdin isn't a real TTY (a detached
Docker container -- this project's primary deployment target, restart:
unless-stopped). That crashed a live deployment during this project's own
MFA-token-renewal cycle, repeatedly re-hitting Garmin's rate-limited login
endpoint on every container restart.

Verified against the actual garminconnect library source
(garminconnect/client.py's resolve_mfa(), which calls prompt_mfa() with no
try/except of its own, and garminconnect/__init__.py's outer Garmin.login(),
whose final handler is `except Exception as e: ... raise
GarminConnectConnectionError(f"Login failed: {e}") from e`) that this fix
doesn't change garmin_login()'s overall control flow or final exception type
at all -- any exception _prompt_mfa() raises gets wrapped into
GarminConnectConnectionError exactly like the original EOFError was, which
garmin_login()'s own except clause already catches. Only the diagnostic
message actually logged changes, from an opaque "EOF when reading a line"
to something a human can act on.
"""

import logging
import os
import sys

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
import requests

from config import Config


def _prompt_mfa() -> str:
    if not sys.stdin.isatty():
        raise RuntimeError(
            "MFA code required to complete Garmin login, but stdin is not an "
            "interactive terminal (this process can't prompt for it). Run "
            "`docker compose run --rm garmin-fetch-data` in an interactive "
            "terminal to complete the MFA prompt once and save a reusable "
            "session token; automatic runs will resume normally afterward."
        )
    return input("MFA one-time code (via email or SMS): ").strip()


def garmin_login(config: Config) -> Garmin:
    token_store_expanded = os.path.expanduser(config.token_dir)
    token_store = token_store_expanded
    if os.path.isfile(token_store_expanded) and (not token_store_expanded.endswith(".json")):
        # New native client treats non-.json token paths as directories.
        # If a legacy file exists at this path, use a dedicated directory instead.
        token_store = token_store_expanded + "_tokens"
        logging.warning(
            "TOKEN_DIR points to an existing file (%s). Using '%s' for native token storage compatibility",
            token_store_expanded,
            token_store,
        )

    try:
        logging.info(f"Trying to login to Garmin Connect using token data from '{token_store}'...")
        garmin = Garmin()
        garmin.login(token_store)
        logging.info("Login to Garmin Connect successful using stored session tokens.")

    except (FileNotFoundError, GarminConnectAuthenticationError, GarminConnectConnectionError):
        logging.warning(
            "Session is expired or login information not present/incorrect. You'll need to log in again...login with your Garmin Connect credentials to generate them."
        )
        try:
            user_email = (config.garminconnect_email or "").strip() or input(
                "Enter Garminconnect Login e-mail: "
            ).strip()
            user_password = (config.garminconnect_password or "").strip() or input(
                "Enter Garminconnect password (characters will be visible): "
            ).strip()
            garmin = Garmin(
                email=user_email,
                password=user_password,
                is_cn=config.garminconnect_is_cn,
                prompt_mfa=_prompt_mfa,
            )
            garmin.login(token_store)

            logging.info(f"Oauth tokens stored in '{token_store}' for future use")
            logging.info(
                "login to Garmin Connect successful using credentials and MFA (if enabled). Continuing with current run"
            )

        except (
            FileNotFoundError,
            GarminConnectConnectionError,
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
            requests.exceptions.HTTPError,
        ) as err:
            logging.error(str(err))
            raise Exception("Garmin login failed after credential/MFA attempt")

    return garmin
