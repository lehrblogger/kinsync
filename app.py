import base64
import hmac
import json
import os
import re
import shutil
import requests
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

FS_COOKIES = os.environ["FS_COOKIES"]
CRON_SECRET = os.environ["CRON_SECRET"]
GITEA_URL = os.environ.get("GITEA_URL", "")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
GITEA_OWNER = os.environ.get("GITEA_OWNER", "")
GITEA_REPO = os.environ.get("GITEA_REPO", "")
GITEA_BRANCH = os.environ.get("GITEA_BRANCH", "main")

RADICALE_COLLECTIONS = "/data/collections/collection-root"
RADICALE_USER = os.environ.get("RADICALE_USER", "")
RADICALE_CALENDAR = os.environ.get("RADICALE_CALENDAR", "four-seasons")

BASE_URL = "https://www.fourseasons.com"
UPCOMING_TRIPS_URL = f"{BASE_URL}/profile/api/upcoming-trips/"
GLOBAL_STATE_URL = f"{BASE_URL}/profile/api/global-state/"
ITINERARY_URL = f"{BASE_URL}/profile/api/itinerary/"

app = Flask(__name__)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True


def ical_escape(text):
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


app.jinja_env.filters["ical_escape"] = ical_escape


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_api_time(date_str, time_str):
    """Parse 'YYYY-MM-DD' + 'HH:MM:SS.sssZ' into a UTC datetime."""
    t = time_str.rstrip("Z").split(".")[0]
    return datetime.strptime(f"{date_str}T{t}", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def prepare_events(itinerary, confirmation_number):
    events = []
    summary = itinerary["bookingSummary"]
    check_in_date = date.fromisoformat(summary["checkInDate"])
    check_out_date = date.fromisoformat(summary["checkOutDate"])
    property_name = summary["propertyName"]
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Multi-day stay event (all-day, spans check-in through check-out)
    events.append({
        "uid": f"{confirmation_number}-stay@fourseasons-calendar",
        "filename": "stay.ics",
        "dtstamp": now_stamp,
        "summary": property_name,
        "allday": True,
        "dtstart": check_in_date.strftime("%Y%m%d"),
        "dtend": (check_out_date + timedelta(days=1)).strftime("%Y%m%d"),
        "location": property_name,
        "description": "",
    })

    # Check-out event (noon, floating/local time since we don't have tz info)
    co_dt = datetime.combine(check_out_date, datetime.strptime("12:00", "%H:%M").time())
    events.append({
        "uid": f"{confirmation_number}-checkout@fourseasons-calendar",
        "filename": "checkout.ics",
        "dtstamp": now_stamp,
        "summary": f"Check Out – {property_name}",
        "allday": False,
        "dtstart": co_dt.strftime("%Y%m%dT%H%M%S"),
        "dtend": (co_dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S"),
        "location": property_name,
        "description": "",
    })

    for i, ti in enumerate(itinerary.get("timelineItems", [])):
        item = ti["item"]
        date_str = ti["date"]

        if item.get("type") == "arrival":
            # checkInTime is "3:15 PM" local time — treat as floating (no tz suffix)
            checkin_str = item.get("checkInTime", "3:00 PM")
            try:
                dt = datetime.strptime(f"{date_str} {checkin_str}", "%Y-%m-%d %I:%M %p")
                dtstart = dt.strftime("%Y%m%dT%H%M%S")
                dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
                allday = False
            except ValueError:
                dtstart = check_in_date.strftime("%Y%m%d")
                dtend = dtstart
                allday = True

            events.append({
                "uid": f"{confirmation_number}-checkin@fourseasons-calendar",
                "filename": "checkin.ics",
                "dtstamp": now_stamp,
                "summary": f"Check In – {property_name}",
                "allday": allday,
                "dtstart": dtstart,
                "dtend": dtend,
                "location": property_name,
                "description": strip_html(item.get("disclaimer", "")),
            })

        else:
            time_str = item.get("time", "")
            allday_date = date.fromisoformat(date_str).strftime("%Y%m%d")
            if not time_str:
                dtstart = allday_date
                dtend = allday_date
                allday = True
            else:
                try:
                    dt = parse_api_time(date_str, time_str)
                    dtstart = dt.strftime("%Y%m%dT%H%M%SZ")
                    dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
                    allday = False
                except (ValueError, AttributeError):
                    dtstart = allday_date
                    dtend = allday_date
                    allday = True

            vendor = item.get("vendorNameOnItinerary", "")
            subtype = item.get("requestSubtype", "")
            event_summary = f"{vendor} ({subtype})" if vendor and subtype else vendor or subtype

            desc_parts = []
            if item.get("description"):
                desc_parts.append(item["description"])
            notes = strip_html(item.get("guestVisibleNotes", ""))
            if notes:
                desc_parts.append(notes)
            cancellation = strip_html(item.get("cancellationPolicy", ""))
            if cancellation:
                desc_parts.append(f"Cancellation: {cancellation}")

            events.append({
                "uid": f"{confirmation_number}-{i}@fourseasons-calendar",
                "filename": f"{i}.ics",
                "dtstamp": now_stamp,
                "summary": event_summary,
                "allday": allday,
                "dtstart": dtstart,
                "dtend": dtend,
                "location": item.get("departureLocation") or item.get("pickupLocation") or "",
                "description": "\n\n".join(desc_parts),
            })

    return events


def list_gitea_dir(confirmation_number: str) -> dict[str, str]:
    """Returns {filename: sha} for all files in the trip's directory."""
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/contents/{confirmation_number}"
    headers = {"Authorization": f"token {GITEA_TOKEN}"}
    resp = requests.get(url, headers=headers, params={"ref": GITEA_BRANCH})
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return {item["name"]: item["sha"] for item in resp.json() if item["type"] == "file"}


def commit_event(confirmation_number: str, filename: str, ics_content: str, existing_sha: str | None = None) -> None:
    file_path = f"{confirmation_number}/{filename}"
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITEA_TOKEN}"}
    payload = {
        "branch": GITEA_BRANCH,
        "content": base64.b64encode(ics_content.encode()).decode(),
        "message": f"Update {file_path}",
    }
    if existing_sha:
        payload["sha"] = existing_sha
        resp = requests.put(url, headers=headers, json=payload)
    else:
        resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()


def delete_gitea_file(file_path: str, sha: str) -> None:
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITEA_TOKEN}"}
    resp = requests.delete(url, headers=headers, json={
        "branch": GITEA_BRANCH,
        "message": f"Remove stale event {file_path}",
        "sha": sha,
    })
    resp.raise_for_status()


def write_to_radicale(confirmation_number: str, events: list) -> None:
    if not RADICALE_USER:
        return
    calendar_dir = Path(f"{RADICALE_COLLECTIONS}/{RADICALE_USER}/{RADICALE_CALENDAR}")
    calendar_dir.mkdir(parents=True, exist_ok=True)
    new_filenames = set()
    for event in events:
        dest_filename = f"{confirmation_number}-{event['filename']}"
        new_filenames.add(dest_filename)
        (calendar_dir / dest_filename).write_text(render_template("event.ics", event=event))
    for f in calendar_dir.glob(f"{confirmation_number}-*.ics"):
        if f.name not in new_filenames:
            f.unlink()
    cache_dir = calendar_dir / ".Radicale.cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def sync_trip_to_gitea(confirmation_number: str, events: list) -> None:
    if not all([GITEA_URL, GITEA_TOKEN, GITEA_OWNER, GITEA_REPO]):
        return
    existing = list_gitea_dir(confirmation_number)
    new_filenames = {event["filename"] for event in events}
    for event in events:
        ics_content = render_template("event.ics", event=event)
        commit_event(confirmation_number, event["filename"], ics_content, existing.get(event["filename"]))
    for filename, sha in existing.items():
        if filename not in new_filenames:
            delete_gitea_file(f"{confirmation_number}/{filename}", sha)


def login(session: requests.Session) -> None:
    session.headers.update({"Cookie": FS_COOKIES})


def get_confirmation_numbers(session: requests.Session) -> list[str]:
    resp = session.get(UPCOMING_TRIPS_URL)
    resp.raise_for_status()
    return [trip["confirmationNumber"] for trip in resp.json()["trips"]]


def get_booking_id(session: requests.Session, confirmation_number: str) -> str:
    resp = session.get(GLOBAL_STATE_URL, params={"orsConfirmationNumber": confirmation_number})
    resp.raise_for_status()
    return resp.json()["activeBookingId"]


def get_itinerary(session: requests.Session, booking_id: str) -> dict:
    resp = session.get(ITINERARY_URL, params={"bookingId": booking_id, "currencyCode": "USD"})
    resp.raise_for_status()
    return resp.json()


@app.route("/run")
def run():
    if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {CRON_SECRET}"):
        abort(401)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })

    login(session)
    confirmation_numbers = get_confirmation_numbers(session)

    for confirmation_number in confirmation_numbers:
        booking_id = get_booking_id(session, confirmation_number)
        itinerary = get_itinerary(session, booking_id)
        events = prepare_events(itinerary, confirmation_number)
        sync_trip_to_gitea(confirmation_number, events)
        write_to_radicale(confirmation_number, events)

    return f"Done. Processed {len(confirmation_numbers)} booking(s)."


@app.route("/debug")
def debug():
    if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {CRON_SECRET}"):
        abort(401)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })

    login(session)
    confirmation_numbers = get_confirmation_numbers(session)

    result = {}
    for confirmation_number in confirmation_numbers:
        booking_id = get_booking_id(session, confirmation_number)
        itinerary = get_itinerary(session, booking_id)
        result[confirmation_number] = itinerary

    return jsonify(result)
