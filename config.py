from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    WANDERLOG_API_URL = 'https://wanderlog.com/api/tripPlans'
    WANDERLOG_COOKIE = os.getenv('WANDERLOG_COOKIE')
    SECRET_KEY = os.getenv('SECRET_KEY')
