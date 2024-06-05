from flask import Flask, jsonify, Response
from config import Config
from ics import Calendar, Event
from datetime import datetime
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
            print(section)
            # e = Event()
            # e.name = event.get('title', 'No Title')
            # e.begin = datetime.fromtimestamp(event.get('startDate') / 1000).isoformat()
            # e.end = datetime.fromtimestamp(event.get('endDate') / 1000).isoformat()
            # e.description = event.get('description', '')
            # calendar.events.add(e)
    return calendar

@app.route('/trips.json')
def trips_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify(trips)

@app.route('/sections.json')
def sections_json():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    return jsonify([section for trip in trips for section in trip.get('tripPlan', {}).get('itinerary', {}).get('sections', [])])

@app.route('/trips.ics')
def trips_ics():
    trips = [fetch_trip(trip_id) for trip_id in fetch_trip_ids()]
    calendar = create_ics(trips)
    return Response(str(calendar), mimetype=f"{'text/plain' if app.debug else 'text/calendar'}")

if __name__ == '__main__':
    app.run(debug=True)
