"""Log line parsers: the eight line formats of dataset/evidence/logs into one LogRecord.

Implements SPEC F9. Every line is `<ISO-ts> <body>`; the first token of the body
selects the format:

* `{`            JSON object (fmt `json`)
* `<PRI>1`       RFC5424 syslog (fmt `syslog`)
* `[`            bracketed `[LVL] [service] [trace] event: kv` (fmt `bracket`)
* `|`            pipe-delimited `| LVL | service | trace | event | kv` (fmt `pipe`)
* `requestId=`   cloud runtime, whose `message="..."` is parsed a second time (fmt `cloud`)
* `LEVEL service=<svc> event=record_lookup`  diag, any level, no trace (fmt `diag`)
* `level=`       logfmt (fmt `logfmt`), or readback (fmt `readback`) when the line
                 has no `instance` key: the readback collector never writes one

`LogRecord.line` is the 1-based line number in the file (0 for a bare `parse_line`).
`kv` holds every key=value pair of the record body (for `cloud`, the inner
message). The literal `null` becomes None. A line without a trace id keeps
`trace=None`: `instance` is never used as a substitute (SPEC F9). The
`log_router` and `readback_collector` framing lines are dropped by `parse_log`.
Ported from kvparse/parse_line of the analysis prototype logparse.

`LogParser` then turns the records of one file into Observations (SPEC F9). Pass 1
collects the subject keys of every `*_started` line per trace id. Pass 2 decodes each
state event of the EVENT_RULES table into one Observation whose keys are the keys of
its trace plus the key fields on the line itself. Joining is by trace id, never by
adjacency. Events in NOISE_EVENTS are dropped, services outside a rule's `services`
(the profile_service decoys) are dropped and counted, and any other event is reported
in the parse notes as `unknown_event`. Ported from classify/observe of the analysis
prototype; the category names are the deletion_rules.csv names.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from ghostaudit.evidence.base import ParseError, ParseOutput
from ghostaudit.keys import keys_from_record
from ghostaudit.model import RESULT_STATES, ManifestEntry, ObsState, Observation
from ghostaudit.timeutil import to_epoch

FMT_LOGFMT = "logfmt"
FMT_READBACK = "readback"
FMT_JSON = "json"
FMT_SYSLOG = "syslog"
FMT_BRACKET = "bracket"
FMT_PIPE = "pipe"
FMT_CLOUD = "cloud"
FMT_DIAG = "diag"

FRAMING_SERVICES = frozenset({"log_router", "readback_collector"})
NULL_LITERAL = "null"

_KV_RE = re.compile(r'([A-Za-z_][\w.]*)=("((?:[^"\\]|\\.)*)"|\S+)')
_UNESCAPE_RE = re.compile(r'\\(["\\])')
_SYSLOG_RE = re.compile(r"<\d+>1 \S+ (\S+) (\S+) - - (.*)")
_BRACKET_RE = re.compile(r"\[(\w+)\] \[([^\]]+)\] \[([^\]]+)\] (\w+): ?(.*)")
_PIPE_RE = re.compile(r"\| (\w+) \| (\S+) \| (\S+) \| (\S+)(?: \| (.*))?")
_DIAG_RE = re.compile(r"(DEBUG|INFO|WARN|ERROR) (service=\S+ event=record_lookup\b.*)")

KV = Dict[str, Optional[str]]


@dataclass(frozen=True)
class LogRecord:
    """One parsed log line; the fields the formats lack are None."""

    ts: int
    fmt: str
    level: Optional[str]
    service: Optional[str]
    trace: Optional[str]
    event: Optional[str]
    kv: KV
    line: int = 0


def parse_log(text: str) -> Tuple[LogRecord, ...]:
    """Parse a whole log file in line order, skipping blank and framing lines."""
    records: List[LogRecord] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = parse_line(line)
        except ParseError as error:
            raise ParseError("line %d: %s" % (number, error)) from None
        if not is_framing(record):
            records.append(replace(record, line=number))
    return tuple(records)


def is_framing(record: LogRecord) -> bool:
    """True for log_router and readback_collector export header/trailer lines."""
    return record.service in FRAMING_SERVICES


def parse_line(line: str) -> LogRecord:
    """Parse one non-empty log line; ParseError when no format matches (SPEC F9)."""
    stamp, _, body = line.rstrip("\n").partition(" ")
    try:
        ts = to_epoch(stamp)
    except ValueError as error:
        raise ParseError(str(error)) from None
    if body.startswith("{"):
        return _parse_json(ts, body)
    if body.startswith("<"):
        return _parse_syslog(ts, body)
    if body.startswith("["):
        return _parse_bracket(ts, body)
    if body.startswith("|"):
        return _parse_pipe(ts, body)
    if body.startswith("requestId="):
        return _parse_cloud(ts, body)
    diag = _DIAG_RE.fullmatch(body)
    if diag:
        kv = _parse_kv(diag.group(2))
        return LogRecord(ts, FMT_DIAG, diag.group(1), kv.get("service"), None, kv.get("event"), kv)
    if body.startswith("level="):
        return _parse_logfmt(ts, body)
    raise ParseError("unrecognised log line format: %r" % line[:80])


def _parse_kv(text: str) -> KV:
    """All key=value pairs of `text`; quoted values are unescaped, `null` is None."""
    pairs: KV = {}
    for match in _KV_RE.finditer(text):
        quoted = match.group(3)
        value = match.group(2) if quoted is None else _UNESCAPE_RE.sub(r"\1", quoted)
        pairs[match.group(1)] = None if value == NULL_LITERAL else value
    return pairs


def _parse_logfmt(ts: int, body: str) -> LogRecord:
    kv = _parse_kv(body)
    fmt = FMT_LOGFMT if "instance" in kv else FMT_READBACK
    level, service, trace, event = (kv.get(k) for k in ("level", "service", "trace_id", "event"))
    return LogRecord(ts, fmt, level, service, trace, event, kv)


def _parse_json(ts: int, body: str) -> LogRecord:
    try:
        data = json.loads(body)
    except ValueError as error:
        raise ParseError("invalid JSON: %s" % error) from None
    if not isinstance(data, dict):
        raise ParseError("JSON log line is not an object")
    kv: KV = {}
    for key, value in data.items():
        if value is not None and not isinstance(value, str):
            raise ParseError("JSON field %r is not a string" % key)
        kv[key] = None if value == NULL_LITERAL else value
    return LogRecord(
        ts, FMT_JSON, kv.get("severity"), kv.get("service"), kv.get("trace_id"), kv.get("event"), kv
    )


def _parse_syslog(ts: int, body: str) -> LogRecord:
    match = _SYSLOG_RE.fullmatch(body)
    if match is None:
        raise ParseError("malformed syslog line: %r" % body[:80])
    kv = _parse_kv(match.group(3))
    host_service, trace = match.group(1), match.group(2)
    return LogRecord(ts, FMT_SYSLOG, kv.get("level"), host_service, trace, kv.get("event"), kv)


def _parse_bracket(ts: int, body: str) -> LogRecord:
    match = _BRACKET_RE.fullmatch(body)
    if match is None:
        raise ParseError("malformed bracket line: %r" % body[:80])
    level, service, trace, event, rest = match.groups()
    return LogRecord(ts, FMT_BRACKET, level, service, trace, event, _parse_kv(rest))


def _parse_pipe(ts: int, body: str) -> LogRecord:
    match = _PIPE_RE.fullmatch(body)
    if match is None:
        raise ParseError("malformed pipe line: %r" % body[:80])
    level, service, trace, event, rest = match.groups()
    return LogRecord(ts, FMT_PIPE, level, service, trace, event, _parse_kv(rest or ""))


def _parse_cloud(ts: int, body: str) -> LogRecord:
    outer = _parse_kv(body)
    inner = _parse_kv(outer.get("message") or "")
    level, service, trace = (outer.get(k) for k in ("level", "function", "requestId"))
    return LogRecord(ts, FMT_CLOUD, level, service, trace, inner.get("event"), inner)


LOG_SUFFIX = ".log"
STARTED_SUFFIX = "_started"
RECORD_LOOKUP_EVENT = "record_lookup"
TRUE = "true"
FALSE = "false"
REDACTED_TEXT = "[REDACTED]"

# SPEC F9: fields of a `*_started` line that name the subject of the whole trace.
START_KEY_FIELDS = (
    "lookup_key",
    "match_key",
    "subject_ref",
    "subject_key",
    "scan_key",
    "owner_key",
)
# SPEC F9: key fields that sit on a state line itself. A line's own START_KEY_FIELDS
# count too: `message_read` carries `subject_ref` and the support_replica contact
# query carries `lookup_key` directly on the line that names the resource.
INLINE_KEY_FIELDS = (
    "correlation_key",
    "matched_value",
    "customer_email",
    "email",
    "requester_email",
    "owner_email",
    "customer_reference",
    "subject_reference",
)
# Fields that must all be null for a record to count as anonymized or redacted.
ANALYTICS_IDENTIFIERS = ("customer_reference", "email", "phone", "email_hash")
REQUESTER_FIELDS = ("requester_email", "requester_name", "requester_phone")

# Auxiliary events that never change resource state (SPEC F9 noise); the set is enumerated
# from the 26 log files, and anything outside it and EVENT_RULES is an `unknown_event`.
NOISE_EVENTS = frozenset(
    {
        "cache_lookup",
        "cache_refresh",
        "certificate_checked",
        "checkpoint_saved",
        "connection_acquired",
        "connection_pool_pressure",
        "consumer_lag",
        "delivery_abandoned",
        "dependency_recovered",
        "dependency_retry",
        "disk_latency",
        "flag_snapshot_loaded",
        "lease_extended",
        "lease_renewed",
        "pool_sample",
        "properties_reloaded",
        "slow_call_rate",
        "telemetry_flushed",
        "thumbnail_failed",
        "timer_tick",
    }
)

Decoder = Callable[[KV], ObsState]
TraceKeys = Dict[str, FrozenSet[str]]


def _text(kv: KV, name: str) -> str:
    value = kv.get(name)
    if value is None:
        raise ValueError("missing field %r" % name)
    return value


def _flag(kv: KV, name: str) -> bool:
    value = _text(kv, name)
    if value not in (TRUE, FALSE):
        raise ValueError("%s must be true or false, got %r" % (name, value))
    return value == TRUE


def _mapped(name: str, states: Dict[str, ObsState]) -> Decoder:
    """Decoder that maps the value of field `name` through `states`."""

    def decode(kv: KV) -> ObsState:
        value = _text(kv, name)
        if value not in states:
            raise ValueError("unsupported %s=%r" % (name, value))
        return states[value]

    return decode


def _switch(name: str, on: ObsState, off: ObsState) -> Decoder:
    """Decoder whose state follows the boolean field `name`."""
    return lambda kv: on if _flag(kv, name) else off


def _always(state: ObsState) -> Decoder:
    return lambda kv: state


def _all_null(fields: Tuple[str, ...], cleared: ObsState, exposed: ObsState) -> Decoder:
    """`cleared` when every named field is null, else `exposed`."""
    return lambda kv: cleared if all(kv.get(f) is None for f in fields) else exposed


def _direct_identifiers(kv: KV) -> ObsState:
    count = _text(kv, "direct_identifiers")
    if not count.isdigit():
        raise ValueError("direct_identifiers must be a count, got %r" % count)
    return ObsState.ANONYMIZED if int(count) == 0 else ObsState.EXPOSED


def _restore_candidate(kv: KV) -> ObsState:
    restorable = _flag(kv, "eligible") and not _flag(kv, "deletion_block")
    return ObsState.ACTIVE if restorable else ObsState.BLOCKED


def _message_read(kv: KV) -> ObsState:
    if _text(kv, "message_text") != REDACTED_TEXT:
        raise ValueError("message_text is not %s" % REDACTED_TEXT)
    return ObsState.REDACTED


def _contact_marker(kv: KV) -> ObsState:
    if _flag(kv, "marker_found"):
        raise ValueError("a found deletion marker has no defined state")
    return ObsState.PRESENT


@dataclass(frozen=True)
class EventRule:
    """How one event decodes: owning system, category, state, and the services that emit it."""

    system_id: str
    category: Optional[str]
    decode: Decoder
    services: FrozenSet[str]


def _rule(
    system_id: str, category: Optional[str], decode: Decoder, services: Optional[Set[str]] = None
) -> EventRule:
    return EventRule(system_id, category, decode, frozenset(services or {system_id}))


_ROWS = {"0": ObsState.ABSENT, "1": ObsState.PRESENT}
_ROWS_STATE = _mapped("rows", _ROWS)
_EXPOSED = _always(ObsState.EXPOSED)
_PRESENT = _always(ObsState.PRESENT)
_ENABLED = _switch("enabled", ObsState.ACTIVE, ObsState.DISABLED)
_AVAILABLE = _switch("available", ObsState.PRESENT, ObsState.ABSENT)
_RESTORE_ALLOWED = _switch("restore_allowed", ObsState.ACTIVE, ObsState.BLOCKED)
_ANALYTICS_CLEARED = _all_null(ANALYTICS_IDENTIFIERS, ObsState.ANONYMIZED, ObsState.EXPOSED)
_REQUESTER_CLEARED = _all_null(REQUESTER_FIELDS, ObsState.REDACTED, ObsState.EXPOSED)
_INDEX_HIT = _mapped("result", {"hit": ObsState.PRESENT})
_OPT_IN = _mapped("email_opt_in", {TRUE: ObsState.PRESENT})
_RESTORE_DENIED = _mapped("decision", {"deny": ObsState.BLOCKED})

# SPEC F9 state table. profile_lookup_completed is accepted from account_service only,
# which drops the profile_service decoys.
EVENT_RULES: Dict[str, EventRule] = {
    "profile_lookup_completed": _rule("account_service", "USER_PROFILE", _ROWS_STATE),
    "index_query_completed": _rule("search_service", "SEARCH_INDEX_ENTRY", _INDEX_HIT),
    "audit_record_read_completed": _rule("security_service", "SECURITY_AUDIT_LOG", _ROWS_STATE),
    "analytics_identity_scan": _rule("analytics_platform", "ANALYTICS_PROFILE", _EXPOSED),
    "analytics_profile_read": _rule("analytics_platform", "ANALYTICS_PROFILE", _direct_identifiers),
    "analytics_profile_read_completed": _rule(
        "analytics_platform", "ANALYTICS_PROFILE", _ANALYTICS_CLEARED
    ),
    "contact_lookup_completed": _rule("analytics_platform", "SECONDARY_IDENTIFIER", _OPT_IN),
    "message_pii_scan": _rule("support_platform", "SUPPORT_MESSAGE", _EXPOSED),
    "attachment_pii_scan": _rule("support_platform", "SUPPORT_ATTACHMENT", _PRESENT),
    "message_read": _rule("support_platform", "SUPPORT_MESSAGE", _message_read),
    # A generic ticket read: message or attachment is left to the activity event type.
    "support_ticket_read_completed": _rule("support_platform", None, _REQUESTER_CLEARED),
    "connector_heartbeat": _rule("integration_service", "DATA_FLOW", _ENABLED),
    "connector_config_loaded": _rule("integration_service", "DATA_FLOW", _ENABLED),
    "connector_config_read_completed": _rule("integration_service", "DATA_FLOW", _ENABLED),
    "restore_candidate_evaluated": _rule("backup_service", "BACKUP_ARCHIVE", _restore_candidate),
    "restore_authorization_completed": _rule("backup_service", "BACKUP_ARCHIVE", _RESTORE_DENIED),
    "restore_policy_read_completed": _rule("backup_service", "BACKUP_ARCHIVE", _RESTORE_ALLOWED),
    "export_download_check_completed": _rule("export_service", "USER_EXPORT", _AVAILABLE),
    "export_metadata_read_completed": _rule("export_service", "USER_EXPORT", _AVAILABLE),
    "retained_order_loaded": _rule("legal_service", "LEGAL_HOLD_RECORD", _PRESENT),
    # The support_replica copy has no category: policy falls back to the activity event type.
    "contact_query_completed": _rule("support_platform", None, _ROWS_STATE, {"support_replica"}),
    "deletion_marker_check": _rule("support_platform", None, _contact_marker, {"support_replica"}),
}


class LogParser:
    """Claims `.log` evidence and decodes it into Observations (SPEC F9)."""

    name = "log_lines"

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        """True for a `.log` file."""
        return entry.path.suffix == LOG_SUFFIX

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        """Decode the whole file; ParseError when it is not UTF-8 or a line is malformed."""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ParseError("%s is not UTF-8 text: %s" % (entry.file_id, error)) from error
        return log_observations(entry, parse_log(text))


def trace_keys(records: Tuple[LogRecord, ...]) -> TraceKeys:
    """Subject keys of the `*_started` lines, grouped by trace id (SPEC F9 pass 1)."""
    found: Dict[str, Set[str]] = defaultdict(set)
    for record in records:
        if record.trace is not None and (record.event or "").endswith(STARTED_SUFFIX):
            found[record.trace] |= _line_keys(record, START_KEY_FIELDS)
    return {trace: frozenset(keys) for trace, keys in found.items()}


def _line_keys(record: LogRecord, fields: Tuple[str, ...]) -> Set[str]:
    return set(keys_from_record([record.kv.get(field) for field in fields]))


def log_observations(entry: ManifestEntry, records: Tuple[LogRecord, ...]) -> ParseOutput:
    """One Observation per state event; skipped lines and unknown events go to the notes."""
    joined = trace_keys(records)
    observations: List[Observation] = []
    notes: List[str] = []
    dropped: Counter = Counter()
    for record in records:
        event = record.event
        if event in NOISE_EVENTS or (event or "").endswith(STARTED_SUFFIX):
            continue
        locator = "%s:L%d" % (entry.file_id, record.line)
        if event != RECORD_LOOKUP_EVENT and event not in EVENT_RULES:
            notes.append("%s unknown_event %s/%s" % (locator, record.service, event))
            continue
        try:
            observation = _observation(entry, record, locator, joined)
        except ValueError as error:
            notes.append("%s skipped: %s" % (locator, error))
            continue
        if observation is None:
            dropped[(record.service, event)] += 1
        else:
            observations.append(observation)
    for (service, event), count in sorted(dropped.items()):
        notes.append("dropped %d %s/%s lines from an unexpected service" % (count, service, event))
    return ParseOutput(observations=tuple(observations), notes=tuple(notes))


def _observation(
    entry: ManifestEntry, record: LogRecord, locator: str, joined: TraceKeys
) -> Optional[Observation]:
    """Decode one state line; None when its service is not the rule's (a decoy)."""
    decoded = _decode(record)
    if decoded is None:
        return None
    system_id, category, state = decoded
    keys = _line_keys(record, INLINE_KEY_FIELDS + START_KEY_FIELDS)
    keys |= joined.get(record.trace or "", frozenset())
    return Observation(
        file_id=entry.file_id,
        captured_at=entry.captured_at,
        entry_time=record.ts,
        system_id=system_id,
        resource_id=_text(record.kv, "resource_id"),
        category=category,
        state=state,
        subject_keys=frozenset(keys),
        locator=locator,
    )


def _decode(record: LogRecord) -> Optional[Tuple[str, Optional[str], ObsState]]:
    """(system_id, category, state) of a state line; ValueError for an unsupported value."""
    kv = record.kv
    if record.event == RECORD_LOOKUP_EVENT:
        result = _text(kv, "result")
        if result not in RESULT_STATES:
            raise ValueError("unknown result %r" % result)
        return _text(kv, "system"), kv.get("record_type"), RESULT_STATES[result]
    rule = EVENT_RULES[record.event or ""]
    if record.service not in rule.services:
        return None
    return rule.system_id, rule.category, rule.decode(kv)
