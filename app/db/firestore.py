import os
import firebase_admin
from firebase_admin import credentials, firestore

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
SA_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

def initialize_db():
    if not firebase_admin._apps:
        if os.getenv("ENVIRONMENT") == "development":
            if os.path.exists(SA_KEY_PATH):
                cred = credentials.Certificate(SA_KEY_PATH)
                firebase_admin.initialize_app(cred, {'projectId': PROJECT_ID})
                print(f"🔥 Connected to Firestore locally: {PROJECT_ID}")
            else:
                firebase_admin.initialize_app(options={'projectId': PROJECT_ID})
                print(f"☁️ Connected via Default Identity (Project: {PROJECT_ID})")
        else:
            firebase_admin.initialize_app(options={'projectId': PROJECT_ID})
            print(f"☁️ Connected via Default Identity (Project: {PROJECT_ID})")
    return firestore.client()

db = initialize_db()