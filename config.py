from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    TRIP_ID = os.getenv('TRIP_ID')
