from flask import Flask, jsonify, Response
from config import Config
from ics import Calendar, Event
from datetime import datetime, timedelta
import requests

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
                     placeName = block.get('place', {}).get('name')
                     startTime = block.get('startTime')
                     texts = block.get('text', {}).get('ops', [])
                     title = texts[0].get('insert', '').split('\n')[0].strip('.') if texts else placeName
                     if block.get('type') == 'place' and placeName and startTime:
                        e = Event()
                        e.name = title
                        e.location = placeName
                        e.begin = datetime.strptime(f'{date} {startTime}', '%Y-%m-%d %H:%M')
                        endTime = block.get('endTime')
                        if endTime:
                            e.end =  datetime.strptime(f'{date} {endTime}', '%Y-%m-%d %H:%M')
                        else:
                            e.end = e.begin + timedelta(minutes=1)
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
