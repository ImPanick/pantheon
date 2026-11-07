# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calendar-domain tool implementations.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Holds the manage_calendar tool (CalDAV-backed event CRUD).
``src.tool_implementations`` re-exports these for backward compatibility.
"""
import json
import logging
import re
from typing import Dict, Optional

from src.tools._common import _parse_tool_args
from src.tool_utils import get_upload_handler
from src.upload_handler import reserve_upload_references

logger = logging.getLogger(__name__)


async def do_manage_calendar(content: str, owner: Optional[str] = None) -> Dict:
    """Handle manage_calendar tool calls: list/create/update/delete calendar events (local SQLite)."""
    from datetime import datetime, timedelta, timezone
    from core.database import SessionLocal, CalendarCal, CalendarEvent, Note
    from routes.calendar_routes import (
        _ensure_default_calendar,
        _ensure_positive_duration,
        _parse_dt_pair,
        parse_due_for_user,
        _resolve_base_uid,
        _push_caldav_event_after_commit,
        _record_caldav_delete_tombstone,
    )
    import uuid as _uuid

    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    # ── Batch normalization ──
    # Some models (e.g. deepseek-v4-flash) emit {"events": [{...}, ...]}
    # instead of individual create_event calls. Iterate and create each.
    if isinstance(args.get("events"), list) and not args.get("action"):
        results = []
        for ev in args["events"]:
            if not isinstance(ev, dict):
                continue
            # Normalize start/end from {dateTime: "..."} object to flat string
            for field, target in [("start", "dtstart"), ("end", "dtend")]:
                val = ev.pop(field, None)
                if val and target not in ev:
                    ev[target] = val.get("dateTime", val) if isinstance(val, dict) else val
            ev.setdefault("action", "create_event")
            r = await do_manage_calendar(json.dumps(ev), owner=owner)
            results.append(r)
        created = [r for r in results if r.get("exit_code") == 0 and not r.get("error")]
        failed = [r for r in results if r.get("error")]

        if not results:
            return {"error": "No events to create", "exit_code": 1}

        # Surface both successes and failures
        parts = []
        if created:
            summaries = [r.get("response", "") for r in created]
            parts.append(f"Created {len(created)} event(s):\n" + "\n".join(summaries))
        if failed:
            first_error = failed[0].get("error", "Unknown error")
            parts.append(f"Failed to create {len(failed)} event(s). First error: {first_error}")

        response = "\n\n".join(parts)
        # Non-zero exit code for partial or total failure
        exit_code = 0 if not failed else 1
        return {"response": response, "exit_code": exit_code, "created_count": len(created), "failed_count": len(failed)}

    # Normalize action — some models emit hyphens ("list-calendars") instead
    # of underscores. Treat them as equivalent so we don't bounce a
    # cosmetic typo back to the model and waste a round-trip. Also accept
    # short forms (`create`, `update`, `delete`) as aliases for the
    # full `<verb>_event` names — models keep emitting the short forms.
    action = (args.get("action") or "list_events").replace("-", "_").strip().lower()
    _ACTION_ALIASES = {
        "create": "create_event",
        "update": "update_event",
        "delete": "delete_event",
        "list": "list_events",
    }
    action = _ACTION_ALIASES.get(action, action)
    db = SessionLocal()

    def _calendar_query():
        q = db.query(CalendarCal)
        if owner is not None:
            q = q.filter(CalendarCal.owner == owner)
        return q

    def _event_query():
        q = db.query(CalendarEvent).join(CalendarCal)
        if owner is not None:
            q = q.filter(CalendarCal.owner == owner)
        return q

    def _event_uid_candidates(raw_uid) -> list:
        """`B1907`. The uid as given, then the uid inside an event anchor.

        Replies write an event as `[Summary](#event-<uid>)`, and list_events and
        create_event print the same anchors, so a model copies `#event-<uid>`
        (or `event-<uid>`) into `uid`. The exact text is tried first, so a real
        uid that begins with `event-` still finds itself.
        """
        text = str(raw_uid or "").strip()
        candidates = [text]
        if text.startswith("#event-"):
            candidates.append(text[len("#event-"):])
        elif text.startswith("event-"):
            candidates.append(text[len("event-"):])
        return [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]

    def _find_event(raw_uid):
        """`(event, series uid, None)` for the event `raw_uid` names, or
        `(None, "", error)` with the error the tool has always answered."""
        malformed = None
        for index, candidate in enumerate(_event_uid_candidates(raw_uid)):
            try:
                candidate_base = _resolve_base_uid(candidate)
            except ValueError as e:
                if index == 0:
                    malformed = str(e)
                continue
            found = _event_query().filter(CalendarEvent.uid == candidate_base).first()
            if found is not None:
                return found, candidate_base, None
        return None, "", malformed or f"Event {raw_uid} not found"

    def _no_reminder_value(value) -> bool:
        return value is None or value is False or (isinstance(value, str) and not value.strip())

    def _reminder_minutes(raw_args) -> Optional[int]:
        # `B1909`: 0 ("at the event's start", which the Calendar offers) is a
        # value. An `or` chain skipped it as falsy, and `0 in (None, "", False)`
        # is True in Python, so it came back as no reminder.
        raw = next((raw_args.get(name) for name in (
            "reminder_minutes", "remind_before_minutes", "alarm_minutes", "reminder", "alarm",
        ) if not _no_reminder_value(raw_args.get(name))), None)
        if raw in (None, ""):
            desc = str(raw_args.get("description") or "")
            if re.search(r"\b(remind|reminder|alarm)\b", desc, re.I):
                raw = desc
        if _no_reminder_value(raw):
            return None
        if raw is True:
            return 10
        if isinstance(raw, (int, float)):
            return max(0, int(raw))
        text = str(raw).strip().lower()
        if text in {"none", "no", "off", "false"}:
            return None
        # `(?<!\d)`, `B1919`: a number is tried from its first digit only. From
        # every digit, a long run of them was read once per digit.
        m = re.search(r"(?<!\d)(\d+)\s*(?:minutes?|mins?|m)\b", text)
        if m:
            return max(0, int(m.group(1)))
        m = re.search(r"(?<!\d)(\d+)\s*(?:hours?|hrs?|h)\b", text)
        if m:
            return max(0, int(m.group(1)) * 60)
        if text.isdigit():
            return max(0, int(text))
        return None

    def _event_description(raw_args, minutes_before: Optional[int]) -> str:
        desc = str(raw_args.get("description", "") or "")
        if minutes_before is None:
            return desc
        # `(?::\s*)?`, `B1919`: one whitespace run before the number, not two
        # side by side that split a long run every possible way.
        reminder_only = re.compile(
            r"^\s*(?:remind(?:er)?|alarm)\s*(?::\s*)?\d+\s*"
            r"(?:minutes?|mins?|m|hours?|hrs?|h)\b.*$",
            re.I,
        )
        return "" if reminder_only.match(desc) else desc

    def _parse_event_dt(raw: str) -> tuple[datetime, bool]:
        """Parse agent event datetimes in the user's timezone when available."""
        return _parse_dt_pair(parse_due_for_user(raw))

    def _parse_all_day_event_dt(raw: str, *, end: bool = False) -> tuple[datetime, bool]:
        """`B1909`. An all-day date is the person's calendar day, not an instant.

        `_parse_event_dt` read `2026-10-24` as the person's midnight and stored
        its UTC instant, which east of UTC is the day before, so a birthday the
        agent added was shown, listed and synced a day early. The day is kept
        as written, stored as wall time like every other all-day row. An end
        later in its day keeps that day (all-day ends are exclusive).
        """
        text = str(raw or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text), False
        wall = datetime.fromisoformat(parse_due_for_user(text)).replace(tzinfo=None)
        day = wall.replace(hour=0, minute=0, second=0, microsecond=0)
        if end and wall > day:
            day += timedelta(days=1)
        return day, False

    def _first_nonempty_arg(*names: str):
        for name in names:
            value = args.get(name)
            if value not in (None, ""):
                return value
        return None

    def _create_calendar_reminder(summary: str, location: str, dtstart: datetime,
                                  all_day: bool, minutes_before: int,
                                  is_utc: bool = False) -> tuple[Optional[str], Optional[str]]:
        remind_at = dtstart - timedelta(minutes=minutes_before)
        # `B1909`: a row that is not UTC (an all-day day) is the person's wall
        # time, so it is compared with their clock; with no zone known that is
        # the server's, as before.
        from src.user_time import now_user_local
        now = datetime.utcnow() if is_utc else now_user_local().replace(tzinfo=None)
        if dtstart <= now:
            return None, "event already passed"
        if remind_at <= now:
            # If the requested "before" time already passed but the event is
            # still upcoming, create an immediate Note reminder instead of
            # silently dropping it.
            remind_at = now
        start_fmt = dtstart.strftime("%a %b %d") if all_day else dtstart.strftime("%a %b %d %H:%M")
        loc = f" @ {location}" if location else ""
        text = f"{summary}{loc} — {start_fmt}"
        due_date = remind_at.isoformat() + ("Z" if is_utc else "")
        expected_title = f"Reminder: {summary}"
        existing_q = db.query(Note).filter(
            Note.archived == False,  # noqa: E712
            Note.due_date == due_date,
        )
        if owner is not None:
            existing_q = existing_q.filter(Note.owner == owner)
        target_title = re.sub(r"^\s*reminder\s*:\s*", "", expected_title.strip().lower())
        for existing in existing_q.limit(25).all():
            existing_title = re.sub(r"^\s*reminder\s*:\s*", "", (existing.title or "").strip().lower())
            if existing_title == target_title:
                return existing.id, "duplicate reminder already exists"
        note = Note(
            id=str(_uuid.uuid4()),
            owner=owner,
            title=expected_title,
            items=json.dumps([{"text": text, "done": False, "checked": False}]),
            note_type="todo",
            label="calendar",
            due_date=due_date,
            source="calendar",
        )
        db.add(note)
        return note.id, None

    def _delete_calendar_reminders(ev) -> int:
        """`B1909`. Delete the reminder notes `_create_calendar_reminder` made for `ev`.

        A reminder is a Note, so deleting its event left it to fire for an
        event that no longer exists. A note is this event's when the calendar
        made it, it carries this event's reminder title, and it falls due in
        the week before the event starts, in the frame the event is stored in.
        The title alone would take a same-named reminder of another event.
        """
        if not ev.dtstart or not (ev.summary or "").strip():
            return 0
        q = db.query(Note).filter(
            Note.source == "calendar",
            Note.archived == False,  # noqa: E712
            Note.title == f"Reminder: {ev.summary}",
            Note.due_date.isnot(None),
        )
        q = q.filter(Note.owner == owner) if owner is not None else q.filter(Note.owner.is_(None))
        removed = 0
        for note in q.all():
            text = str(note.due_date).strip()
            try:
                due = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
            except ValueError:
                continue
            if due.tzinfo is not None:
                due = due.astimezone(timezone.utc).replace(tzinfo=None)
            if ev.dtstart - timedelta(days=7) <= due <= ev.dtstart:
                db.delete(note)
                removed += 1
        return removed

    try:
        if action == "list_calendars":
            _ensure_default_calendar(db, owner)
            # This read path intentionally persists the lazily-created default;
            # event creation commits it in the event's transaction instead.
            db.commit()
            cals = _calendar_query().all()
            result = [{"name": c.name, "href": c.id} for c in cals]
            if result:
                lines = [f"Found {len(result)} calendar(s):"]
                for c in result:
                    lines.append(f"- {c['name']} ({c['href'][:8]})")
                response_text = "\n".join(lines)
            else:
                response_text = "No calendars found."
            return {"response": response_text, "calendars": result, "exit_code": 0}

        elif action == "list_events":
            try:
                start_raw = _first_nonempty_arg(
                    "start", "start_time", "start_date", "range_start", "from", "dtstart", "since"
                )
                end_raw = _first_nonempty_arg(
                    "end", "end_time", "end_date", "range_end", "to", "dtend", "until"
                )
                query_raw = args.get("query") or args.get("date_range") or args.get("range")
                if query_raw and (not start_raw or not end_raw):
                    return {
                        "error": (
                            "list_events needs explicit start/end ISO datetimes; "
                            f"resolve the requested range ({query_raw!r}) and call manage_calendar again."
                        ),
                        "exit_code": 1,
                    }
                # `B1908`: the bounds are the person's. A timed row with a zone
                # is stored as a UTC instant, and an all-day or floating row as
                # wall time, so each bound is read both ways: the UTC instant of
                # the person's time for the first, their wall time for the
                # second. With no zone known both are the reading this always
                # made, so a background run is unchanged.
                from src.user_time import (
                    get_user_tz_name, get_user_tz_offset, now_user_local, user_timezone,
                )
                zone_known = get_user_tz_offset() is not None or bool(get_user_tz_name())

                def _bound(raw):
                    aware = parse_due_for_user(raw)
                    utc_b, is_aware = _parse_dt_pair(aware)
                    if zone_known and is_aware:
                        local_b = datetime.fromisoformat(aware).astimezone(user_timezone())
                        return utc_b, local_b.replace(tzinfo=None)
                    return utc_b, utc_b

                if start_raw:
                    start_utc, start_local = _bound(start_raw)
                elif zone_known:
                    midnight = now_user_local().replace(hour=0, minute=0, second=0, microsecond=0)
                    start_local = midnight.replace(tzinfo=None)
                    start_utc = midnight.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    start_utc = start_local = datetime.utcnow().replace(
                        hour=0, minute=0, second=0, microsecond=0)
                if end_raw:
                    end_utc, end_local = _bound(end_raw)
                else:
                    end_utc = start_utc + timedelta(days=14)
                    end_local = start_local + timedelta(days=14)
            except ValueError as e:
                return {"error": f"Invalid date format: {e}", "exit_code": 1}

            if end_utc <= start_utc:
                end_utc = start_utc + timedelta(days=1)
            if end_local <= start_local:
                end_local = start_local + timedelta(days=1)

            from sqlalchemy import and_, or_
            q = _event_query().filter(
                or_(
                    and_(
                        CalendarEvent.is_utc == True,  # noqa: E712
                        or_(CalendarEvent.all_day == False,  # noqa: E712
                            CalendarEvent.all_day.is_(None)),
                        CalendarEvent.dtstart < end_utc,
                        CalendarEvent.dtend > start_utc,
                    ),
                    and_(
                        or_(CalendarEvent.is_utc == False,  # noqa: E712
                            CalendarEvent.all_day == True),  # noqa: E712
                        CalendarEvent.dtstart < end_local,
                        CalendarEvent.dtend > start_local,
                    ),
                ),
                CalendarEvent.status != "cancelled",
            )
            calendar_filter = args.get("calendar")
            if calendar_filter:
                q = q.filter(
                    (CalendarEvent.calendar_id == calendar_filter) |
                    (CalendarCal.name == calendar_filter)
                )
            rows = q.order_by(CalendarEvent.dtstart).all()
            events = []
            for ev in rows:
                if ev.all_day:
                    s, e = ev.dtstart.strftime("%Y-%m-%d"), ev.dtend.strftime("%Y-%m-%d")
                else:
                    suffix = "Z" if getattr(ev, "is_utc", False) else ""
                    s, e = ev.dtstart.isoformat() + suffix, ev.dtend.isoformat() + suffix
                events.append({
                    "uid": ev.uid, "summary": ev.summary or "", "dtstart": s, "dtend": e,
                    "all_day": ev.all_day, "description": ev.description or "",
                    "location": ev.location or "",
                    "calendar": ev.calendar.name if ev.calendar else "",
                    "calendar_href": ev.calendar_id,
                    "event_type": ev.event_type or "",
                    "importance": ev.importance or "normal",
                    "rrule": ev.rrule or "",
                })
            if not events:
                response_text = f"No events between {start_local.date().isoformat()} and {end_local.date().isoformat()}."
            else:
                lines = [f"Found {len(events)} event(s) between {start_local.date().isoformat()} and {end_local.date().isoformat()}:"]
                for ev in events:
                    when = ev["dtstart"]
                    when_str = f"{when} (all day)" if ev.get("all_day") else f"{when} -> {ev.get('dtend', '')}"
                    # Clickable anchor — opens the calendar on the event's day.
                    line = f"- {when_str}: [{ev['summary']}](#event-{ev['uid']})"
                    if ev.get("event_type"):
                        line += f" #{ev['event_type']}"
                    if ev.get("importance") and ev["importance"] != "normal":
                        line += f" !{ev['importance']}"
                    if ev.get("rrule"):
                        line += f" repeats({ev['rrule']})"
                    if ev.get("location"):
                        line += f" @ {ev['location']}"
                    if ev.get("calendar"):
                        line += f" ({ev['calendar']})"
                    if ev.get("description"):
                        desc = ev["description"].strip().replace("\n", " ")
                        if len(desc) > 120:
                            desc = desc[:117] + "..."
                        line += f"\n    {desc}"
                    lines.append(line)
                response_text = "\n".join(lines)
            return {"response": response_text, "events": events, "exit_code": 0}

        elif action == "create_event":
            summary = args.get("summary")
            # Accept the various names models like to use for the start
            # field: dtstart (canonical), start, start_time, when.
            dtstart_str = (args.get("dtstart") or args.get("start")
                           or args.get("start_time") or args.get("when"))
            if not summary or not dtstart_str:
                return {"error": "summary and dtstart are required", "exit_code": 1}

            # Accept either an href OR a calendar name/short-id like "Main"
            # or "62e545d8" — saves the model from having to memorize hrefs
            # after a `list_calendars` call returned short prefixes.
            cal_href = args.get("calendar_href") or args.get("calendar")
            cal = None
            if cal_href:
                cal = (_calendar_query()
                       .filter(CalendarCal.id == cal_href)
                       .first())
                if not cal:
                    # Try by name (case-insensitive) or by short-id prefix
                    cal = (_calendar_query()
                           .filter(CalendarCal.name.ilike(cal_href))
                           .first())
                if not cal:
                    cal = (_calendar_query()
                           .filter(CalendarCal.id.like(f"{cal_href}%"))
                           .first())
            if not cal:
                cal = _ensure_default_calendar(db, owner)

            all_day = bool(args.get("all_day", False))
            try:
                dtstart, dtstart_is_utc = (
                    _parse_all_day_event_dt(dtstart_str) if all_day else _parse_event_dt(dtstart_str)
                )
            except ValueError as e:
                return {"error": f"Could not parse dtstart {dtstart_str!r}: {e}", "exit_code": 1}
            dtend_raw = args.get("dtend") or args.get("end") or args.get("end_time")
            if dtend_raw:
                try:
                    if all_day:
                        # `B1909`: an end on the start's own day is that one day.
                        dtend, dtend_is_utc = _parse_all_day_event_dt(dtend_raw, end=True)
                        dtend = _ensure_positive_duration(dtstart, dtend, True)
                    else:
                        dtend, dtend_is_utc = _parse_event_dt(dtend_raw)
                    dtstart_is_utc = dtstart_is_utc or dtend_is_utc
                except ValueError as e:
                    return {"error": f"Could not parse dtend {dtend_raw!r}: {e}", "exit_code": 1}
            else:
                # Support duration: "1h", "30m", "90min", "1hr30m"
                dur = (args.get("duration") or "").strip().lower()
                delta = None
                if dur:
                    import re as _re_d
                    # From a number's first digit only (`B1919`).
                    h = _re_d.search(r'(?<!\d)(\d+)\s*(?:h|hr|hours?)', dur)
                    m = _re_d.search(r'(?<!\d)(\d+)\s*(?:m|min|minutes?)', dur)
                    secs = (int(h.group(1)) * 3600 if h else 0) + (int(m.group(1)) * 60 if m else 0)
                    if secs > 0:
                        delta = timedelta(seconds=secs)
                if delta is not None:
                    dtend = dtstart + delta
                elif all_day:
                    dtend = dtstart + timedelta(days=1)
                else:
                    dtend = dtstart + timedelta(hours=1)

            # Dedup: if a non-cancelled event with the same title + start time already
            # exists, return its UID instead of creating a fresh copy. Prevents the
            # email triage from multiplying events when several emails reference the
            # same meeting. Compare case-insensitively since LLM-extracted titles
            # can vary in capitalisation.
            from sqlalchemy import func as _func
            existing = (
                _event_query()
                .filter(
                    CalendarEvent.dtstart == dtstart,
                    CalendarEvent.status != "cancelled",
                    _func.lower(CalendarEvent.summary) == summary.lower(),
                )
                .first()
            )
            if existing is not None:
                reminder_note_id = None
                reminder_skipped_reason = None
                minutes_before = _reminder_minutes(args)
                if minutes_before is not None:
                    reminder_note_id, reminder_skipped_reason = _create_calendar_reminder(
                        existing.summary or summary,
                        existing.location or "",
                        existing.dtstart,
                        existing.all_day,
                        minutes_before,
                        bool(existing.is_utc),
                    )
                    if reminder_note_id:
                        db.commit()
                reminder_text = ""
                if minutes_before is not None:
                    reminder_text = (
                        f"; reminder set {minutes_before} min before"
                        if reminder_note_id
                        else f"; reminder not set ({reminder_skipped_reason or 'reminder time already passed'})"
                    )
                return {
                    "response": (
                        f"Event already exists: '{summary}' on {dtstart_str}"
                        + reminder_text
                    ),
                    "uid": existing.uid,
                    "reminder_note_id": reminder_note_id,
                    "reminder_skipped_reason": reminder_skipped_reason,
                    "duplicate": True,
                    "exit_code": 0,
                }

            # Optional tag/category and importance — friendly aliases.
            event_type = (args.get("event_type") or args.get("tag")
                          or args.get("category") or args.get("type") or "") or None
            importance = args.get("importance") or "normal"
            minutes_before = _reminder_minutes(args)

            event_description = _event_description(args, minutes_before)
            event_location = args.get("location", "") or ""
            missing_id = reserve_upload_references(
                get_upload_handler(),
                owner,
                event_description,
                event_location,
            )
            if missing_id:
                return {
                    "error": f"Referenced upload is no longer available: {missing_id}",
                    "exit_code": 1,
                }

            uid = str(_uuid.uuid4())
            ev = CalendarEvent(
                uid=uid, calendar_id=cal.id, summary=summary,
                description=event_description,
                location=event_location,
                dtstart=dtstart, dtend=dtend, all_day=all_day,
                is_utc=dtstart_is_utc and not all_day,
                rrule=args.get("rrule", "") or "",
                event_type=event_type,
                importance=importance,
                caldav_sync_pending="create" if cal.source == "caldav" else None,
            )
            db.add(ev)
            reminder_note_id = None
            reminder_skipped_reason = None
            if minutes_before is not None:
                reminder_note_id, reminder_skipped_reason = _create_calendar_reminder(
                    summary,
                    args.get("location", "") or "",
                    dtstart,
                    all_day,
                    minutes_before,
                    dtstart_is_utc and not all_day,
                )
            db.commit()
            if cal.source == "caldav":
                await _push_caldav_event_after_commit(owner, uid, "create")
            tag_blurb = f" [{event_type}]" if event_type else ""
            if minutes_before is None:
                reminder_blurb = ""
            elif reminder_note_id:
                reminder_blurb = f" with reminder {minutes_before} min before"
            else:
                reminder_blurb = f" without reminder ({reminder_skipped_reason or 'reminder time already passed'})"
            # Return a clickable anchor so the agent can surface a link
            # that opens the calendar on that day. See the markdown
            # anchor convention ([Name](#event-<uid>)).
            return {
                "response": f"Created event [{summary}](#event-{uid}){tag_blurb} on {dtstart_str}{reminder_blurb}",
                "uid": uid,
                "anchor": f"[{summary}](#event-{uid})",
                "reminder_note_id": reminder_note_id,
                "reminder_skipped_reason": reminder_skipped_reason,
                "exit_code": 0,
            }

        elif action == "update_event":
            uid = args.get("uid")
            if not uid:
                return {"error": "uid is required", "exit_code": 1}
            ev, base_uid, lookup_error = _find_event(uid)
            if not ev:
                return {"error": lookup_error, "exit_code": 1}
            missing_id = reserve_upload_references(
                get_upload_handler(),
                owner,
                args.get("description"),
                args.get("location"),
            )
            if missing_id:
                return {
                    "error": f"Referenced upload is no longer available: {missing_id}",
                    "exit_code": 1,
                }
            if args.get("summary") is not None:
                ev.summary = args["summary"]
            if args.get("description") is not None:
                ev.description = args["description"]
            if args.get("location") is not None:
                ev.location = args["location"]
            prev_span = (ev.dtend - ev.dtstart) if (ev.dtstart and ev.dtend) else None
            prev_all_day = bool(ev.all_day)
            _eff_all_day = (
                args["all_day"] if args.get("all_day") is not None else ev.all_day
            )
            if args.get("dtstart") is not None:
                # Anchor naive/natural-language input to the USER's timezone and
                # refresh is_utc, exactly like create_event. Parsing with the
                # raw server-local _parse_dt here (and never touching is_utc)
                # silently shifted an updated event by the user's UTC offset.
                # `B1909`: an all-day date is kept as its calendar day.
                ev.dtstart, _su = (
                    _parse_all_day_event_dt(args["dtstart"]) if _eff_all_day
                    else _parse_event_dt(args["dtstart"])
                )
                ev.is_utc = bool(_su and not _eff_all_day)
                if args.get("dtend") is None:
                    # `B1907`: a new start with no end moves the event and keeps
                    # its length; the old end stayed, so a later start ended
                    # before it began. A changed all-day flag takes create_event's
                    # default span.
                    if bool(_eff_all_day) == prev_all_day and prev_span and prev_span > timedelta(0):
                        ev.dtend = ev.dtstart + prev_span
                    else:
                        ev.dtend = ev.dtstart + (timedelta(days=1) if _eff_all_day else timedelta(hours=1))
            if args.get("dtend") is not None:
                if _eff_all_day:
                    ev.dtend, _eu = _parse_all_day_event_dt(args["dtend"], end=True)
                    ev.dtend = _ensure_positive_duration(ev.dtstart, ev.dtend, True)
                else:
                    ev.dtend, _eu = _parse_event_dt(args["dtend"])
            if args.get("all_day") is not None:
                ev.all_day = args["all_day"]
            # Tag/category + importance updates (any of these aliases).
            _tag = (args.get("event_type") or args.get("tag")
                    or args.get("category") or args.get("type"))
            if _tag is not None:
                ev.event_type = _tag or None
            if args.get("importance") is not None:
                ev.importance = args["importance"]
            if args.get("rrule") is not None:
                ev.rrule = args.get("rrule") or ""
            elif str(args.get("repeat") or "").strip().lower() in {"none", "no", "off", "false", "single"}:
                ev.rrule = ""
            is_caldav = ev.calendar and ev.calendar.source == "caldav"
            if is_caldav:
                ev.caldav_sync_pending = "update"
            db.commit()
            if is_caldav:
                await _push_caldav_event_after_commit(owner, base_uid, "update")
            return {"response": f"Updated event {uid}", "exit_code": 0}

        elif action == "delete_event":
            uid = args.get("uid")
            if not uid:
                return {"error": "uid is required", "exit_code": 1}
            ev, base_uid, lookup_error = _find_event(uid)
            if not ev:
                return {"error": lookup_error, "exit_code": 1}
            is_caldav = ev.calendar and ev.calendar.source == "caldav" and ev.remote_href
            if is_caldav:
                _record_caldav_delete_tombstone(db, ev, owner)
            _delete_calendar_reminders(ev)  # `B1909`
            db.delete(ev)
            db.commit()
            if is_caldav:
                await _push_caldav_event_after_commit(owner, base_uid, "delete")
            return {"response": f"Deleted event {uid}", "exit_code": 0}

        else:
            return {
                "error": f"Unknown action: {action}. Use list_events, create_event, update_event, delete_event, list_calendars",
                "exit_code": 1,
            }

    except Exception as e:
        db.rollback()
        logger.error(f"manage_calendar error: {e}")
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()
