import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def get_db():
    database_url = os.getenv("DATABASE_URL")
    
    if database_url:
        conn = psycopg2.connect(database_url)
    else:
        conn = psycopg2.connect(
            dbname="iga_chatbot",
            user=os.getenv("USER"),
            host="localhost"
        )
    return conn