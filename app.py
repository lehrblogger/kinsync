import hmac
import os
import re
import requests
from datetime import date, datetime, timedelta, timezone
from flask import Flask, abort, render_template, request
from dotenv import load_dotenv

load_dotenv()

FS_COOKIES = os.environ["FS_COOKIES"]
CRON_SECRET = os.environ["CRON_SECRET"]

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
                "dtstamp": now_stamp,
                "summary": event_summary,
                "allday": allday,
                "dtstart": dtstart,
                "dtend": dtend,
                "location": item.get("departureLocation") or item.get("pickupLocation") or "",
                "description": "\n\n".join(desc_parts),
            })

    return events


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
        ics_content = render_template("itinerary.ics", events=events)
        # TODO: commit ics_content to repo as {confirmation_number}.ics

    return f"Done. Processed {len(confirmation_numbers)} booking(s)."
