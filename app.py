import hmac
import json
import os
import re
import shutil
import subprocess
import requests
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

FS_COOKIES = os.environ["FS_COOKIES"]
CRON_SECRET = os.environ["CRON_SECRET"]
COOKIES_FILE = "/data/fs_cookies.txt"

RADICALE_COLLECTIONS = "/data/collections/collection-root"
RADICALE_SYNC_USER = os.environ["RADICALE_SYNC_USER"]
RADICALE_CALENDAR = os.environ.get("RADICALE_CALENDAR", "four-seasons")
GIT_REMOTE_URL = os.environ.get("GIT_REMOTE_URL", "")

# Maps Four Seasons property slug (propertyAnalytics.id) to IANA timezone.
# Times in the FS API use a misleading Z suffix but are actually local property times.
PROPERTY_TIMEZONES = {
    # Hawaii
    "hualalai": "Pacific/Honolulu",
    "lanai": "Pacific/Honolulu",
    "maui": "Pacific/Honolulu",
    "oahu": "Pacific/Honolulu",
    # US West Coast
    "beverly-hills": "America/Los_Angeles",
    "beverly-wilshire": "America/Los_Angeles",
    "los-angeles": "America/Los_Angeles",
    "westlake-village": "America/Los_Angeles",
    "san-francisco": "America/Los_Angeles",
    "silicon-valley": "America/Los_Angeles",
    "palo-alto": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "san-diego": "America/Los_Angeles",
    "santa-barbara": "America/Los_Angeles",
    # US Mountain
    "denver": "America/Denver",
    "jackson-hole": "America/Denver",
    "vail": "America/Denver",
    "santa-fe": "America/Denver",
    "scottsdale": "America/Phoenix",
    # US Central
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "austin": "America/Chicago",
    "st-louis": "America/Chicago",
    "new-orleans": "America/Chicago",
    "nashville": "America/Chicago",
    # US East Coast
    "new-york": "America/New_York",
    "boston": "America/New_York",
    "baltimore": "America/New_York",
    "philadelphia": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "fort-lauderdale": "America/New_York",
    "orlando": "America/New_York",
    "palm-beach": "America/New_York",
    "washington-dc": "America/New_York",
    "naples": "America/New_York",
    # Canada
    "toronto": "America/Toronto",
    "montreal": "America/Toronto",
    "vancouver": "America/Vancouver",
    "whistler": "America/Vancouver",
    # Mexico & Caribbean
    "los-cabos": "America/Mazatlan",
    "costa-palmas": "America/Mazatlan",
    "mexico-city": "America/Mexico_City",
    "punta-mita": "America/Mexico_City",
    "tamarindo": "America/Costa_Rica",
    "costa-rica": "America/Costa_Rica",
    "bahamas": "America/Nassau",
    "anguilla": "America/Anguilla",
    "nevis": "America/St_Kitts",
    "puerto-rico": "America/Puerto_Rico",
    # South America
    "bogota": "America/Bogota",
    "cartagena": "America/Bogota",
    "buenos-aires": "America/Argentina/Buenos_Aires",
    # Europe
    "paris": "Europe/Paris",
    "megeve": "Europe/Paris",
    "london": "Europe/London",
    "hampshire": "Europe/London",
    "milan": "Europe/Rome",
    "florence": "Europe/Rome",
    "taormina": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "mallorca": "Europe/Madrid",
    "lisbon": "Europe/Lisbon",
    "geneva": "Europe/Zurich",
    "gstaad": "Europe/Zurich",
    "budapest": "Europe/Budapest",
    "prague": "Europe/Prague",
    "athens": "Europe/Athens",
    "istanbul": "Europe/Istanbul",
    "baku": "Asia/Baku",
    "french-riviera": "Europe/Paris",
    # Middle East
    "dubai": "Asia/Dubai",
    "abu-dhabi": "Asia/Dubai",
    "amaala": "Asia/Riyadh",
    "red-sea": "Asia/Riyadh",
    "riyadh": "Asia/Riyadh",
    "doha": "Asia/Qatar",
    "kuwait": "Asia/Kuwait",
    "bahrain": "Asia/Bahrain",
    "beirut": "Asia/Beirut",
    "amman": "Asia/Amman",
    "cairo": "Africa/Cairo",
    "sharm-el-sheikh": "Africa/Cairo",
    "alexandria": "Africa/Cairo",
    # Africa
    "marrakech": "Africa/Casablanca",
    "casablanca": "Africa/Casablanca",
    "rabat": "Africa/Casablanca",
    "tunis": "Africa/Tunis",
    "mauritius": "Indian/Mauritius",
    "seychelles": "Indian/Mahe",
    "johannesburg": "Africa/Johannesburg",
    # Asia
    "hong-kong": "Asia/Hong_Kong",
    "macao": "Asia/Macau",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "guangzhou": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "dalian": "Asia/Shanghai",
    "tianjin": "Asia/Shanghai",
    "suzhou": "Asia/Shanghai",
    "hangzhou": "Asia/Shanghai",
    "hoi-an": "Asia/Ho_Chi_Minh",
    "tokyo": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "bangkok": "Asia/Bangkok",
    "chiang-mai": "Asia/Bangkok",
    "koh-samui": "Asia/Bangkok",
    "kuala-lumpur": "Asia/Kuala_Lumpur",
    "langkawi": "Asia/Kuala_Lumpur",
    "singapore": "Asia/Singapore",
    "bali": "Asia/Makassar",
    "jakarta": "Asia/Jakarta",
    "mumbai": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "maldives": "Indian/Maldives",
    "maldives-landaa-giraavaru": "Indian/Maldives",
    "maldives-kuda-huraa": "Indian/Maldives",
    "maldives-voavah": "Indian/Maldives",
    "palau": "Pacific/Palau",
    # Pacific
    "sydney": "Australia/Sydney",
    "bora-bora": "Pacific/Tahiti",
}

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


def parse_duration_hours(duration_str):
    """Parse FS duration strings like '1 Hour', '2.5 hours', '45 minutes', 'Approx. 2.5 Hours'.
    Returns float hours, or None if unparseable (e.g. '2 days')."""
    if not duration_str:
        return None
    s = re.sub(r"approx\.?\s*", "", duration_str.lower()).strip()
    if re.search(r"\d+\s*days?", s):
        return None
    hours = 0.0
    h = re.search(r"(\d+(?:\.\d+)?)\s*hours?", s)
    if h:
        hours += float(h.group(1))
    m = re.search(r"(\d+)\s*min", s)
    if m:
        hours += int(m.group(1)) / 60
    return hours if hours > 0 else None


def parse_api_time(date_str, time_str):
    """Parse 'YYYY-MM-DD' + 'HH:MM:SS.sssZ' into a naive local datetime.
    The Z suffix in FS API responses is misleading — times are local property time."""
    t = time_str.rstrip("Z").split(".")[0]
    return datetime.strptime(f"{date_str}T{t}", "%Y-%m-%dT%H:%M:%S")


def _item_location(item, property_name):
    pickup = item.get("pickupLocation", "")
    dropoff = item.get("dropoffLocation", "")
    if pickup and dropoff:
        return f"{pickup} → {dropoff}"
    return item.get("departureLocation") or pickup or dropoff or property_name


def prepare_events(itinerary, confirmation_number):
    events = []
    summary = itinerary["bookingSummary"]
    check_in_date = date.fromisoformat(summary["checkInDate"])
    check_out_date = date.fromisoformat(summary["checkOutDate"])
    property_name = summary["propertyName"]
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tzid = PROPERTY_TIMEZONES.get(itinerary.get("propertyAnalytics", {}).get("id", ""))

    def make_timed(dt, duration_hours=1):
        """Return (dtstart, dtend, allday=False) using TZID if known, else floating."""
        fmt = "%Y%m%dT%H%M%S"
        return dt.strftime(fmt), (dt + timedelta(hours=duration_hours)).strftime(fmt), False

    # Multi-day stay event (all-day, spans check-in through check-out)
    events.append({
        "uid": f"{confirmation_number}-stay@fourseasons-calendar",
        "filename": "stay.ics",
        "dtstamp": now_stamp,
        "summary": property_name,
        "allday": True,
        "tzid": None,
        "dtstart": check_in_date.strftime("%Y%m%d"),
        "dtend": (check_out_date + timedelta(days=1)).strftime("%Y%m%d"),
        "location": property_name,
        "description": "",
    })

    # Check-out event (noon local time)
    co_dt = datetime.combine(check_out_date, datetime.strptime("12:00", "%H:%M").time())
    co_start, co_end, _ = make_timed(co_dt)
    events.append({
        "uid": f"{confirmation_number}-checkout@fourseasons-calendar",
        "filename": "checkout.ics",
        "dtstamp": now_stamp,
        "summary": f"Check Out – {property_name}",
        "allday": False,
        "tzid": tzid,
        "dtstart": co_start,
        "dtend": co_end,
        "location": property_name,
        "description": "",
    })

    for i, ti in enumerate(itinerary.get("timelineItems", [])):
        item = ti["item"]
        date_str = ti["date"]

        if item.get("type") == "arrival":
            checkin_str = item.get("checkInTime", "3:00 PM")
            try:
                dt = datetime.strptime(f"{date_str} {checkin_str}", "%Y-%m-%d %I:%M %p")
                dtstart, dtend, allday = make_timed(dt)
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
                "tzid": tzid,
                "dtstart": dtstart,
                "dtend": dtend,
                "location": property_name,
                "description": strip_html(item.get("disclaimer", "")),
            })

        else:
            time_str = item.get("time", "")
            allday_date = date.fromisoformat(date_str).strftime("%Y%m%d")
            default_duration = 2 if item.get("requestType") == "Dining" else 1
            duration_hours = parse_duration_hours(item.get("duration", "")) or default_duration
            if not time_str:
                dtstart = allday_date
                dtend = allday_date
                allday = True
                event_tzid = None
            else:
                try:
                    dt = parse_api_time(date_str, time_str)
                    dtstart, dtend, allday = make_timed(dt, duration_hours)
                    event_tzid = tzid
                except (ValueError, AttributeError):
                    dtstart = allday_date
                    dtend = allday_date
                    allday = True
                    event_tzid = None

            vendor = item.get("vendorNameOnItinerary", "")
            subtype = item.get("requestSubtype", "")
            event_summary = f"{vendor} ({subtype})" if vendor and subtype else vendor or subtype

            meta = []
            if item.get("confirmationNumber"):
                meta.append(f"Confirmation: {item['confirmationNumber']}")
            if item.get("totalGuests"):
                meta.append(f"Guests: {item['totalGuests']}")
            elif item.get("numberOfGuests"):
                meta.append(f"Guests: {item['numberOfGuests']}")
            if item.get("totalCost") is not None:
                currency = item.get("currencyCode", "USD")
                meta.append(f"Cost: {currency} {item['totalCost']:,.2f}")
            if item.get("dropoffLocation"):
                meta.append(f"Drop-off: {item['dropoffLocation']}")
            if item.get("vehicleSelected"):
                meta.append(f"Vehicle: {item['vehicleSelected']}")

            desc_parts = []
            if meta:
                desc_parts.append("\n".join(meta))
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
                "tzid": event_tzid,
                "dtstart": dtstart,
                "dtend": dtend,
                "location": _item_location(item, property_name),
                "description": "\n\n".join(desc_parts),
            })

    return events



def git_commit_and_push(message: str) -> None:
    if not GIT_REMOTE_URL:
        return
    repo = RADICALE_COLLECTIONS
    try:
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
        diff = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"], capture_output=True)
        if diff.returncode == 0:
            return  # nothing to commit
        subprocess.run(["git", "-C", repo, "commit", "-m", message], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "push", "--force", "origin", "HEAD:main"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        app.logger.error("Git push failed: %s", e.stderr.decode(errors="replace"))


def write_to_radicale(confirmation_number: str, events: list) -> None:
    calendar_dir = Path(f"{RADICALE_COLLECTIONS}/{RADICALE_SYNC_USER}/{RADICALE_CALENDAR}")
    calendar_dir.mkdir(parents=True, exist_ok=True)
    new_filenames = set()
    def without_dtstamp(content):
        return "\n".join(l for l in content.splitlines() if not l.startswith("DTSTAMP:"))

    for event in events:
        dest_filename = f"{confirmation_number}-{event['filename']}"
        new_filenames.add(dest_filename)
        dest_path = calendar_dir / dest_filename
        new_content = render_template("event.ics", event=event)
        if dest_path.exists() and without_dtstamp(dest_path.read_text()) == without_dtstamp(new_content):
            continue
        dest_path.write_text(new_content)
    for f in calendar_dir.glob(f"{confirmation_number}-*.ics"):
        if f.name not in new_filenames:
            f.unlink()
    cache_dir = calendar_dir / ".Radicale.cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    git_commit_and_push(f"Sync {confirmation_number}")



def get_cookies() -> str:
    try:
        return Path(COOKIES_FILE).read_text().strip()
    except FileNotFoundError:
        return FS_COOKIES


def login(session: requests.Session) -> None:
    session.headers.update({"Cookie": get_cookies()})


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


@app.route("/cookies", methods=["POST"])
def cookies():
    if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {CRON_SECRET}"):
        abort(401)
    value = request.get_data(as_text=True).strip()
    if not value:
        abort(400)
    Path(COOKIES_FILE).write_text(value)
    return "Cookies updated.\n"


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
    try:
        confirmation_numbers = get_confirmation_numbers(session)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return "FS cookies have expired. Update them via POST /cookies.", 403
        raise

    for confirmation_number in confirmation_numbers:
        booking_id = get_booking_id(session, confirmation_number)
        itinerary = get_itinerary(session, booking_id)
        events = prepare_events(itinerary, confirmation_number)
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
