import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
SA_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

def initialize_db():
    if not firebase_admin._apps:
        # 1. Local Dev: Use Key File if it exists
        if SA_KEY_PATH and os.path.exists(SA_KEY_PATH):
            cred = credentials.Certificate(SA_KEY_PATH)
            firebase_admin.initialize_app(cred, {'projectId': PROJECT_ID})
            print(f"🔥 Connected to Firestore (Key): {PROJECT_ID}")
        
        # 2. Production (Cloud Run): Use Default Identity
        else:
            firebase_admin.initialize_app(options={'projectId': PROJECT_ID})
            print(f"☁️ Connected to Firestore (ADC): {PROJECT_ID}")
            
    return firestore.client()

db = initialize_db()