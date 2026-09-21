"""
Characterization tests for fit_decoder.decode_fit(), run against real FIT
files pulled from Johannes's own Garmin Connect history via the project's
own KEEP_FIT_FILES backfill mechanism (see garmin_grafana_phase7_fit_plan
memory / issue #26) -- not hand-invented mock data.

These files live outside the repo (real GPS/health data, never committed)
at FIT_TEST_CORPUS_DIR (default /ext/garmin-grafana/fit_filestore). CI has
no such directory, so every test here skips cleanly when the corpus is
absent -- these assertions exist to characterize decode_fit()'s real
behavior during development, not to gate CI. The eventual single,
scrubbed, committed fixture (still to be sourced, see the memory file) is
what gives this module CI coverage.

Assertions are deliberately about *shape and pattern*, never about
specific values, IDs, or timestamps from any one file -- the corpus grows
over time and files vary in what they contain (e.g. length_mesgs only
appears in pool-swim files), so tests describe what must hold across any
real file of a given kind, not what one particular file happens to say.

Each real file is decoded exactly once per test session (module-scoped
fixture) -- the corpus includes multi-hour rides with 30k+ records, and
re-decoding per test function made this suite unreasonably slow.
"""

import datetime
import os
from pathlib import Path

import pytest

from fit_decoder import FitDecodeError, decode_fit

FIT_TEST_CORPUS_DIR = Path(
    os.environ.get("FIT_TEST_CORPUS_DIR", "/ext/garmin-grafana/fit_filestore")
)


def _corpus_paths():
    if not FIT_TEST_CORPUS_DIR.is_dir():
        return []
    return sorted(FIT_TEST_CORPUS_DIR.glob("*.fit"))


@pytest.fixture(scope="module")
def decoded_corpus():
    """{path: decoded messages dict} for every real FIT file in the corpus."""
    paths = _corpus_paths()
    if not paths:
        pytest.skip(
            f"no real FIT files found under {FIT_TEST_CORPUS_DIR} -- "
            "local-only characterization, not a CI gate"
        )
    result = {}
    for path in paths:
        with open(path, "rb") as f:
            result[path] = decode_fit(f.read())
    return result


def test_decode_fit_returns_dict_of_lists_for_every_real_file(decoded_corpus):
    for path, messages in decoded_corpus.items():
        assert isinstance(messages, dict)
        assert messages, f"{path.name}: decoded to an empty messages dict"
        for message_type, entries in messages.items():
            assert isinstance(message_type, str)
            assert isinstance(entries, list), f"{path.name}: {message_type}"
            for entry in entries:
                assert isinstance(entry, dict), f"{path.name}: {message_type}"


def test_message_type_keys_use_mesgs_suffix(decoded_corpus):
    for path, messages in decoded_corpus.items():
        # record_mesgs/session_mesgs are present in every real activity file
        # this project cares about -- not every message type ends in
        # "_mesgs" in principle, but the ones this pipeline reads do.
        assert "record_mesgs" in messages, path.name
        assert "session_mesgs" in messages, path.name
        assert "record" not in messages, path.name
        assert "session" not in messages, path.name


def test_session_mesgs_is_exactly_one_entry_per_file(decoded_corpus):
    for path, messages in decoded_corpus.items():
        assert len(messages["session_mesgs"]) == 1, path.name


def test_record_timestamps_are_timezone_aware_utc_and_non_decreasing(decoded_corpus):
    for path, messages in decoded_corpus.items():
        records = messages["record_mesgs"]
        assert records, path.name
        timestamps = [r["timestamp"] for r in records if r.get("timestamp")]
        assert timestamps, path.name
        for ts in timestamps:
            assert isinstance(ts, datetime.datetime), path.name
            assert ts.tzinfo is not None, (
                f"{path.name}: expected a timezone-aware timestamp "
                "(garmin-fit-sdk default), got a naive one"
            )
        assert timestamps == sorted(timestamps), (
            f"{path.name}: record timestamps are not monotonically "
            "non-decreasing"
        )


def test_position_fields_when_present_are_ints_in_semicircle_range(decoded_corpus):
    seen_any_position = False
    semicircle_max = 2**31
    for path, messages in decoded_corpus.items():
        for r in messages["record_mesgs"]:
            lat = r.get("position_lat")
            lon = r.get("position_long")
            if lat is not None:
                seen_any_position = True
                assert isinstance(lat, int), path.name
                assert -semicircle_max <= lat < semicircle_max, path.name
            if lon is not None:
                seen_any_position = True
                assert isinstance(lon, int), path.name
                assert -semicircle_max <= lon < semicircle_max, path.name
    # Not every activity in the corpus has GPS (e.g. yoga, strength
    # training, indoor cycling) -- only assert the range/type contract
    # holds *when* a position field is present, not that every file has one.
    assert seen_any_position, (
        "no file in the corpus had any GPS data at all -- the corpus may "
        "be too narrow (e.g. indoor-only) to characterize this field"
    )


def test_sport_field_is_a_non_empty_string_when_present(decoded_corpus):
    for path, messages in decoded_corpus.items():
        sport = messages["session_mesgs"][0].get("sport")
        if sport is not None:
            assert isinstance(sport, str) and sport, path.name


def test_length_mesgs_only_appears_for_some_files_and_has_a_shape_when_present(
    decoded_corpus,
):
    seen_length_mesgs = False
    for path, messages in decoded_corpus.items():
        if "length_mesgs" in messages:
            seen_length_mesgs = True
            assert isinstance(messages["length_mesgs"], list)
            assert messages["length_mesgs"], path.name
            for length in messages["length_mesgs"]:
                assert isinstance(length, dict), path.name
    # Disclosed, not asserted as a hard requirement: length_mesgs is a
    # pool-swim-specific message. If the corpus happens not to contain a
    # pool swim yet, this test still passes (nothing to check), but a
    # human should notice the corpus is missing that activity type.
    if not seen_length_mesgs:
        pytest.skip(
            "no file in the corpus produced length_mesgs (pool-swim "
            "specific) -- corpus may not include a lap-swimming activity yet"
        )


def test_unrecognized_fields_come_back_under_an_int_key_not_a_string(decoded_corpus):
    """
    The concrete API difference from fitparse that actually matters to
    this codebase: fetch_activity_GPS reads a field fitparse calls
    "unknown_140" (parsed_record.get("unknown_140")). garmin-fit-sdk has
    no such string key -- unrecognized fields come back keyed by their
    raw integer def_num instead. Confirmed against a real running
    activity's record_mesgs, where fitparse populates "unknown_140" on
    every record.
    """
    found_int_keyed_field = False
    for path, messages in decoded_corpus.items():
        for r in messages["record_mesgs"]:
            int_keys = [k for k in r.keys() if isinstance(k, int)]
            if int_keys:
                found_int_keyed_field = True
                for k in int_keys:
                    assert f"unknown_{k}" not in r, (
                        f"{path.name}: expected no string 'unknown_{k}' "
                        "key alongside the int key -- decode_fit's output "
                        "should never invent fitparse-style names"
                    )
    assert found_int_keyed_field, (
        "no file in the corpus had any field outside Garmin's official "
        "profile -- can't characterize the int-key behavior without one"
    )


def test_decode_fit_raises_on_garbage_bytes():
    with pytest.raises(FitDecodeError):
        decode_fit(b"this is not a fit file" * 20)


def test_decode_fit_raises_on_truncated_real_file(decoded_corpus):
    path = next(iter(decoded_corpus))
    with open(path, "rb") as f:
        data = f.read()
    with pytest.raises(FitDecodeError):
        decode_fit(data[: len(data) // 2])
