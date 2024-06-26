from flask import Flask, jsonify, Response
from config import Config
from ics import Calendar, Event
from ics.grammar.parse import ContentLine
from datetime import datetime, timedelta
import requests
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder

app = Flask(__name__)
app.config.from_object(Config)

@app.route('/')
def hello_world():
    return 'Hello, World!'

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
        for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', []):
            if section.get('mode') == 'dayPlan':
                heading = section.get('heading')
                date = section.get('date')
                if heading and date:
                    e = Event()
                    e.name = heading
                    e.begin = datetime.strptime(date, '%Y-%m-%d')
                    e.make_all_day()
                    e.url = f"https://wanderlog.com/plan/{trip.get('tripPlan', {}).get('key')}/"
                    calendar.events.add(e)
                for block in section.get('blocks', []):
                    if block.get('type') != 'place':
                        continue
                    placeName = block.get('place', {}).get('name')
                    startTime = block.get('startTime')
                    endTime = block.get('endTime')
                    lat = block.get('place', {}).get('geometry', {}).get('location', {}).get('lat')
                    lng = block.get('place', {}).get('geometry', {}).get('location', {}).get('lng')
                    if not placeName or not startTime or not lat or not lng:
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
                        e.name = name_description[0].strip('.').strip()
                        if len(name_description) > 1:
                             e.description = name_description[1].strip()
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

@app.route('/trips.json')
def trips_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify(trips)

@app.route('/sections.json')
def sections_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify([section for trip in trips for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', [])])

@app.route('/blocks.json')
def blocks_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    sections = [section for trip in trips for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', [])]
    return [block 
        for section in sections 
        if section.get('mode') == 'dayPlan' and section.get('blocks')
        for block in section.get('blocks') if block.get('type') == 'place'
    ]

@app.route('/trips.ics')
def trips_ics():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    calendar = create_ics(trips)
    return Response(str(calendar), mimetype=f"{'text/plain' if app.debug else 'text/calendar'}")

if __name__ == '__main__':
    app.run(debug=True)
