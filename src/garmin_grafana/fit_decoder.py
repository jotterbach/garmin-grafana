"""
Thin wrapper around garmin-fit-sdk's Decoder -- the one place that knows
its API. Replaces fitparse (unmaintained since 2025-01-28, bundled profile
stale since v20.8/2019) across garmin_fetch.py, fit_activity_importer.py
and garmin_bulk_importer.py (issue #26).

Confirmed by direct comparison against real production FIT files (see the
garmin_grafana_phase7_fit_plan memory / issue #26 for the full writeup) --
none of this is guessed:
- Messages come back keyed by "<name>_mesgs" (e.g. "record_mesgs"), not the
  bare message name fitparse used (e.g. "record").
- A field not in Garmin's official profile comes back under an INT key --
  the raw def_num, e.g. 140 -- not a string like fitparse's "unknown_140".
- "timestamp" fields are already timezone-aware (UTC) datetimes, unlike
  fitparse's naive ones.
- Decoder.read() never raises on a malformed/truncated file -- it always
  returns (messages, errors), with errors as a list of exception objects
  when something went wrong. decode_fit() raises FitDecodeError when
  errors is non-empty, so callers can keep using try/except the same way
  they did with fitparse.FitParseError.
"""

from garmin_fit_sdk import Decoder, Stream


class FitDecodeError(Exception):
    """Raised when garmin-fit-sdk's Decoder reports one or more errors."""


def decode_fit(fit_bytes: bytes) -> dict[str, list[dict]]:
    stream = Stream.from_byte_array(fit_bytes)
    messages, errors = Decoder(stream).read()
    if errors:
        raise FitDecodeError(f"{len(errors)} error(s) decoding FIT data: {errors}")
    return messages
