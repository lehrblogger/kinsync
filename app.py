from flask import Flask, jsonify
from config import Config
import requests

app = Flask(__name__)
app.config.from_object(Config)

@app.route('/')
def hello_world():
    return 'Hello, World!'

@app.route('/test')
def api_call():
    url = f"https://wanderlog.com/api/tripPlans/{app.config['TRIP_ID']}?clientSchemaVersion=2&registerView=true"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        return jsonify(data)
    else:
        return jsonify({'error': 'Failed to retrieve data'}), response.status_cod

if __name__ == '__main__':
    app.run(debug=True)
