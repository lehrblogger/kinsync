from flask import Flask, Response, abort, jsonify, request
from functools import wraps
from config import Config
from ics import Calendar, Event
from ics.grammar.parse import ContentLine
from datetime import datetime, timedelta
import requests
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder

app = Flask(__name__)
app.config.from_object(Config)

def fetch_trip_ids():
    url = f"{app.config['WANDERLOG_API_URL']}/myProfile"
    headers = {
        'Cookie': app.config['WANDERLOG_COOKIE']
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    tripPlans = response.json().get('tripPlans', [])
    return list(filter(None, [trip.get('key', False) for trip in tripPlans]))

def fetch_trip(trip_id):
    url = f"{app.config['WANDERLOG_API_URL']}/{trip_id}?clientSchemaVersion=2&registerView=true"
    response = requests.get(url) # There's no authentication on this endpoint
    response.raise_for_status()
    return response.json()

def create_ics(trips):
    tf = TimezoneFinder()
    calendar = Calendar()
    for trip in trips:
        # First, collect information about lodging for each day that will be used later for the all day events
        lodging_locs_by_date = {}
        lodging_info_by_date = {}
        lodging_urls_by_date = {}
        for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', []):
            if section.get('mode') == 'placeList' and section.get('type') == 'hotels':
                for block in section.get('blocks'):
                    # Get the name and address
                    name = block.get('place').get('name')
                    formatted_address = block.get('place').get('formatted_address')
                    if not formatted_address.startswith(name):
                        formatted_address = f'{name}, {formatted_address}'
                    # Get the info
                    info = ""
                    confirmation = block.get('hotel').get('confirmationNumber')
                    other_info = ""
                    text_ops = block.get('text', {}).get('ops', [])
                    if text_ops:
                        for text_op in text_ops:
                            link = text_op.get('attributes', {}).get('link', '')
                            if link:
                                other_info += link
                            else:
                                other_info += text_op.get('insert', '')
                    if confirmation:
                        info += f'Confirmation number: {confirmation}'
                    if other_info:
                        info += f'\n\n{other_info}'
                    # Associate the above with each date
                    check_in_date  = datetime.strptime(block.get('hotel').get('checkIn' ), "%Y-%m-%d")
                    check_out_date = datetime.strptime(block.get('hotel').get('checkOut'), "%Y-%m-%d")
                    current_date = check_in_date
                    while current_date < check_out_date:
                        lodging_locs_by_date[current_date.strftime("%Y-%m-%d")] = formatted_address
                        lodging_info_by_date[current_date.strftime("%Y-%m-%d")] = info
                        lodging_urls_by_date[current_date.strftime("%Y-%m-%d")] = block.get('place').get('website', block.get('place').get('url'))
                        current_date += timedelta(days=1)
        for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', []):
            if section.get('mode') == 'dayPlan':
                heading = section.get('heading')
                date = section.get('date')
                if heading and date:
                    e = Event()
                    e.name = heading
                    e.begin = datetime.strptime(date, '%Y-%m-%d')
                    e.make_all_day()
                    e.location = lodging_locs_by_date.get(date)
                    e.description = lodging_info_by_date.get(date)
                    e.url = lodging_urls_by_date.get(date, f"https://wanderlog.com/plan/{trip.get('tripPlan', {}).get('key')}/")
                    calendar.events.add(e)
                for block in section.get('blocks', []):
                    if block.get('type') != 'place':
                        continue
                    placeName = block.get('place', {}).get('name')
                    lat = block.get('place', {}).get('geometry', {}).get('location', {}).get('lat')
                    lng = block.get('place', {}).get('geometry', {}).get('location', {}).get('lng')
                    startTime = block.get('startTime')
                    endTime = block.get('endTime')
                    if not placeName or not lat or not lng or not startTime:
                        continue
                    e = Event()
                    text_ops = block.get('text', {}).get('ops', [])
                    e.name = placeName
                    if text_ops:
                        text = ""
                        for text_op in text_ops:
                            link = text_op.get('attributes', {}).get('link', '')
                            if link:
                                text += link
                            else:
                                text += text_op.get('insert', '')
                        name_description = text.split('\n', 1)
                        name = name_description[0].strip('.').strip()
                        if len(name) > 0:
                            e.name = name
                        if len(name_description) > 1:
                             e.description = name_description[1].strip()
                    e.url = block.get('place').get('website', block.get('place').get('url'))
                    formatted_address = block.get('place').get('formatted_address')
                    if formatted_address:
                        e.location = f'{placeName}, {formatted_address}'
                    else:
                        e.location = placeName
                    tz = ZoneInfo(tf.timezone_at(lng=lng, lat=lat))
                    begin_datetime = datetime.strptime(f'{date} {startTime}', '%Y-%m-%d %H:%M').replace(tzinfo=tz)
                    end_datetime = begin_datetime + timedelta(minutes=1)
                    if endTime:
                        end_datetime = datetime.strptime(f'{date} {endTime}', '%Y-%m-%d %H:%M').replace(tzinfo=tz)
                    e.extra.append(ContentLine(name="DTSTART", params={"TZID": [tz.key]}, value=begin_datetime.strftime('%Y%m%dT%H%M%S')))
                    e.extra.append(ContentLine(name="DTEND"  , params={"TZID": [tz.key]}, value=end_datetime.strftime('%Y%m%dT%H%M%S')))
                    calendar.events.add(e)
    return calendar

def require_secret_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.args.get('secret_key') != app.config['SECRET_KEY']:
            abort(401)  # Unauthorized
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@require_secret_key
def hello_world():
    return 'Hello, World!'

@app.route('/trips.json')
@require_secret_key
def trips_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify(trips)

@app.route('/sections.json')
@require_secret_key
def sections_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify([section for trip in trips for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', [])])

@app.route('/blocks.json')
@require_secret_key
def blocks_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    sections = [section for trip in trips for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', [])]
    return [block 
        for section in sections 
        if section.get('mode') == 'dayPlan' and section.get('blocks')
        for block in section.get('blocks') if block.get('type') == 'place'
    ]

@app.route('/trips.ics')
@require_secret_key
def trips_ics():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    calendar = create_ics(trips)
    return Response(str(calendar), mimetype=f"{'text/plain' if app.debug else 'text/calendar'}")

if __name__ == '__main__':
    app.run(debug=True)
