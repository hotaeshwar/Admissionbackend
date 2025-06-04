from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Form, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
import sqlite3
import uuid
import cv2
import numpy as np
import requests
import base64
from PIL import Image
import re
from datetime import datetime, date, timedelta
import os
import json
import bcrypt
import jwt
from typing import Optional, List, Dict, Any, Tuple
import io
from pydantic import BaseModel, validator
import uvicorn 
import random
import secrets
import string
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI app
app = FastAPI(title="ID Document Age Verification, Aptitude Test & Zoom Meeting System")

# Security
security = HTTPBearer()
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"

# Zoom API Credentials
ZOOM_ACCOUNT_ID = "LkTs4KBfQS-pTHyz2VzwSQ"
ZOOM_CLIENT_ID = "DHHmA231RgKzqHDrI5lTNw"
ZOOM_CLIENT_SECRET = "Koj2zKGIv44wu6dCMIK2XQYUbysOifGO"
ZOOM_USER_ID = "me"

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173"              # Optional: local dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin secret key for registration
ADMIN_SECRET_KEY = "ADMIN_REGISTRATION_SECRET_2024"

# Test configuration
TEST_CONFIG = {
    "duration_minutes": 60,
    "total_questions": 30,
    "passing_score": 60,
    "questions_per_subject": {
        "Mathematics": 6,
        "Science": 6,
        "English": 6,
        "Reasoning": 6,
        "Aptitude": 4,
        "Psychology": 2
    }
}

# OCR Configuration
OCR_CONFIG = {
    "url": "https://api.ocr.space/parse/image",
    "api_key": "helloworld",
}

# Enhanced Pydantic models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    state_id: int

class UserCreateWithRole(BaseModel):
    username: str
    email: str
    password: str
    role: str  # 'teacher', 'student', or 'admin'
    state_id: Optional[int] = None  # Required for teachers/students, optional for admin
    admin_secret_key: Optional[str] = None  # Required only for admin registration

class AdminCreate(BaseModel):
    username: str
    email: str
    password: str
    admin_secret_key: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserLoginWithRole(BaseModel):
    username: str
    password: str
    role: str  # 'teacher', 'student', or 'admin'
    state_id: Optional[int] = None  # Required for teachers and students, not for admin

class PasswordResetRequest(BaseModel):
    username: str

class ResetTokenResponse(BaseModel):
    reset_token: str
    message: str

class PasswordReset(BaseModel):
    token: str
    new_password: str
    confirm_password: str
    
    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v

class ResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None

class TestAnswer(BaseModel):
    question_id: int
    selected_answer: str
    time_taken: int

class TestSubmission(BaseModel):
    answers: List[TestAnswer]

class AdminApproval(BaseModel):
    result_status: str
    comments: Optional[str] = ""

class MeetingCreate(BaseModel):
    topic: str
    start_time: datetime
    duration: Optional[int] = 60
    student_ids: List[str]

class MeetingUpdate(BaseModel):
    topic: Optional[str] = None
    start_time: Optional[datetime] = None
    duration: Optional[int] = None

# Utility functions
def generate_reset_token():
    """Generate a secure, unique reset token"""
    alphabet = string.ascii_letters + string.digits + "@#$%^&*"
    token = ''.join(secrets.choice(alphabet) for _ in range(12))
    return token

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_db_connection():
    conn = sqlite3.connect('verification_system.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_user_id(role: str) -> str:
    """Generate unique user ID based on role"""
    unique_id = str(uuid.uuid4())[:8].upper()
    if role == "teacher":
        return f"TEACH{unique_id}"
    elif role == "student":
        return f"STU{unique_id}"
    else:
        return f"ADMIN{unique_id}"

# Database setup with roles table
def init_db():
    conn = sqlite3.connect('verification_system.db')
    cursor = conn.cursor()
    
    # Roles table - NEW
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            requires_document BOOLEAN DEFAULT TRUE,
            requires_state BOOLEAN DEFAULT TRUE,
            requires_admin_key BOOLEAN DEFAULT FALSE,
            min_age INTEGER,
            max_age INTEGER
        )
    ''')
    
    # States table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS states (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Users table - updated to include reset token fields
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student')),
            state_id INTEGER,
            age INTEGER,
            birthdate TEXT,
            reset_token TEXT,
            reset_token_expires TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (state_id) REFERENCES states (id)
        )
    ''')
    
    # Documents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            extracted_text TEXT,
            birthdate TEXT,
            age INTEGER,
            verification_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Aptitude test questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            category TEXT NOT NULL,
            question TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            difficulty_level INTEGER DEFAULT 1,
            grade_level TEXT DEFAULT '10-12'
        )
    ''')
    
    # Test attempts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_attempts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            test_session_id TEXT NOT NULL,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            total_questions INTEGER,
            correct_answers INTEGER,
            wrong_answers INTEGER,
            unanswered INTEGER,
            score_percentage REAL,
            result_status TEXT DEFAULT 'pending',
            admin_approval TEXT DEFAULT 'pending',
            admin_comments TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id)
        )
    ''')
    
    # Test responses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_responses (
            id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            selected_answer TEXT,
            is_correct BOOLEAN,
            time_taken INTEGER,
            FOREIGN KEY (attempt_id) REFERENCES test_attempts (id),
            FOREIGN KEY (question_id) REFERENCES test_questions (id)
        )
    ''')
    
    # Zoom meetings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            start_time TIMESTAMP NOT NULL,
            duration INTEGER DEFAULT 60,
            join_url TEXT NOT NULL,
            start_url TEXT NOT NULL,
            zoom_meeting_id TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users (id)
        )
    ''')
    
    # Meeting participants table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meeting_participants (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            invitation_sent BOOLEAN DEFAULT FALSE,
            joined_at TIMESTAMP,
            FOREIGN KEY (meeting_id) REFERENCES meetings (id),
            FOREIGN KEY (student_id) REFERENCES users (id),
            UNIQUE(meeting_id, student_id)
        )
    ''')
    
    # Meeting recordings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meeting_recordings (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            recording_url TEXT NOT NULL,
            file_type TEXT DEFAULT 'MP4',
            file_size INTEGER,
            duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (meeting_id) REFERENCES meetings (id)
        )
    ''')
    
    # Insert roles data
    roles_data = [
        ("admin", "Administrator", "System administrator with full access", False, False, True, None, None),
        ("teacher", "Teacher", "Teacher with meeting and student management access", True, True, False, 20, None),
        ("student", "Student", "Student with test taking and meeting access", True, True, False, None, 19)
    ]
    
    cursor.executemany('''
        INSERT OR IGNORE INTO roles 
        (id, name, description, requires_document, requires_state, requires_admin_key, min_age, max_age)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', roles_data)
    
    # Insert states
    states_data = [
        (1, "Delhi"), (2, "Haryana"), (6, "Himachal Pradesh"),
        (7, "Jammu and Kashmir"), (3, "Punjab"), (8, "Rajasthan"),
        (4, "Uttar Pradesh"), (5, "Uttarakhand")
    ]
    
    cursor.executemany('INSERT OR IGNORE INTO states (id, name) VALUES (?, ?)', states_data)
    
    # Insert sample test questions
    sample_questions = get_sample_questions()
    for question in sample_questions:
        cursor.execute('''
            INSERT OR IGNORE INTO test_questions 
            (subject, category, question, option_a, option_b, option_c, option_d, correct_answer, difficulty_level, grade_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', question)
    
    conn.commit()
    conn.close()

def get_sample_questions():
    """Sample aptitude test questions for grades 10-12"""
    return [
        # Mathematics (6 questions)
        ("Mathematics", "Algebra", "If 2x + 5 = 15, what is the value of x?", "5", "10", "15", "20", "A", 1, "10-12"),
        ("Mathematics", "Geometry", "What is the area of a circle with radius 7 cm? (π = 22/7)", "154 cm²", "144 cm²", "164 cm²", "174 cm²", "A", 2, "10-12"),
        ("Mathematics", "Arithmetic", "What is 15% of 200?", "25", "30", "35", "40", "B", 1, "10-12"),
        ("Mathematics", "Trigonometry", "What is the value of sin 30°?", "1/2", "√3/2", "1", "0", "A", 2, "10-12"),
        ("Mathematics", "Statistics", "The mean of 5, 10, 15, 20, 25 is:", "15", "12", "18", "20", "A", 1, "10-12"),
        ("Mathematics", "Algebra", "Solve for y: 3y - 7 = 2y + 8", "15", "12", "10", "8", "A", 2, "10-12"),
        
        # Science (6 questions)
        ("Science", "Physics", "What is the SI unit of force?", "Newton", "Joule", "Watt", "Pascal", "A", 1, "10-12"),
        ("Science", "Chemistry", "What is the chemical formula of water?", "HO", "H2O", "H2O2", "HO2", "B", 1, "10-12"),
        ("Science", "Biology", "What is the powerhouse of the cell?", "Nucleus", "Mitochondria", "Ribosome", "Chloroplast", "B", 1, "10-12"),
        ("Science", "Physics", "The speed of light in vacuum is approximately:", "3×10⁸ m/s", "3×10⁶ m/s", "3×10¹⁰ m/s", "3×10⁴ m/s", "A", 2, "10-12"),
        ("Science", "Chemistry", "Which gas is most abundant in Earth's atmosphere?", "Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen", "C", 1, "10-12"),
        ("Science", "Biology", "Which organ produces insulin in the human body?", "Liver", "Pancreas", "Kidney", "Heart", "B", 2, "10-12"),
        
        # English (6 questions)
        ("English", "Grammar", "Choose the correct sentence:", "He don't like apples", "He doesn't like apples", "He not like apples", "He doesn't likes apples", "B", 1, "10-12"),
        ("English", "Vocabulary", "What is the antonym of 'difficult'?", "Hard", "Easy", "Complex", "Tough", "B", 1, "10-12"),
        ("English", "Comprehension", "If someone is 'optimistic', they are:", "Sad", "Hopeful", "Angry", "Confused", "B", 2, "10-12"),
        ("English", "Grammar", "Choose the correct past tense of 'go':", "Goed", "Gone", "Went", "Going", "C", 1, "10-12"),
        ("English", "Literature", "Who wrote 'Romeo and Juliet'?", "Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain", "B", 2, "10-12"),
        ("English", "Grammar", "Which is the correct plural of 'child'?", "Childs", "Children", "Childes", "Childrens", "B", 1, "10-12"),
        
        # Reasoning (6 questions)
        ("Reasoning", "Logical", "If all roses are flowers and some flowers are red, then:", "All roses are red", "Some roses are red", "No roses are red", "Cannot be determined", "D", 3, "10-12"),
        ("Reasoning", "Analytical", "What comes next in the series: 2, 4, 8, 16, ?", "24", "32", "20", "28", "B", 2, "10-12"),
        ("Reasoning", "Spatial", "If BOOK is coded as CPPL, how is DOOR coded?", "EPPS", "DQQS", "CPPR", "EOQS", "A", 3, "10-12"),
        ("Reasoning", "Logical", "All cats are animals. Some animals are pets. Therefore:", "All cats are pets", "Some cats are pets", "No cats are pets", "Cannot be determined", "D", 3, "10-12"),
        ("Reasoning", "Pattern", "Find the odd one out: 2, 4, 6, 9, 10", "2", "4", "9", "10", "C", 2, "10-12"),
        ("Reasoning", "Sequence", "Complete the series: A, C, E, G, ?", "H", "I", "J", "K", "B", 2, "10-12"),
        
        # Aptitude (6 questions)
        ("Aptitude", "Numerical", "A train travels 60 km in 1 hour. How far will it travel in 2.5 hours?", "120 km", "150 km", "180 km", "200 km", "B", 2, "10-12"),
        ("Aptitude", "Percentage", "If the price of an item increases from ₹50 to ₹60, what is the percentage increase?", "10%", "15%", "20%", "25%", "C", 2, "10-12"),
        ("Aptitude", "Time & Work", "If 5 workers can complete a job in 10 days, how many days will 10 workers take?", "5 days", "15 days", "20 days", "25 days", "A", 3, "10-12"),
        ("Aptitude", "Ratio", "The ratio of boys to girls in a class is 3:2. If there are 15 boys, how many girls are there?", "8", "10", "12", "15", "B", 2, "10-12"),
        ("Aptitude", "Profit & Loss", "An item is sold for ₹120 at a profit of 20%. What was its cost price?", "₹96", "₹100", "₹110", "₹115", "B", 3, "10-12"),
        ("Aptitude", "Speed & Distance", "If a car travels 240 km in 4 hours, what is its average speed?", "50 km/h", "60 km/h", "70 km/h", "80 km/h", "B", 1, "10-12"),
        
        # Psychology (6 questions)
        ("Psychology", "Personality", "In a group project, you prefer to:", "Lead the team", "Support others", "Work independently", "Follow instructions", "A", 1, "10-12"),
        ("Psychology", "Behavior", "When facing a difficult problem, you usually:", "Give up quickly", "Ask for help immediately", "Try different approaches", "Avoid the problem", "C", 2, "10-12"),
        ("Psychology", "Social", "In social situations, you feel most comfortable when:", "You're the center of attention", "You're listening to others", "You're helping someone", "You're observing quietly", "B", 2, "10-12"),
        ("Psychology", "Learning", "Your preferred learning style is:", "Visual (seeing)", "Auditory (hearing)", "Kinesthetic (doing)", "Reading/Writing", "A", 1, "10-12"),
        ("Psychology", "Decision", "When making important decisions, you rely most on:", "Logic and facts", "Emotions and feelings", "Others' opinions", "Past experiences", "A", 2, "10-12"),
        ("Psychology", "Stress", "When you feel stressed, you usually:", "Take a break", "Work harder", "Talk to someone", "Ignore the stress", "A", 2, "10-12"),
    ]

# Initialize database
init_db()

# Zoom utility functions
def get_zoom_access_token() -> Optional[str]:
    """Generates a Zoom API access token."""
    url = "https://zoom.us/oauth/token"
    credentials = f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT_ID}
    
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        print(f"New Zoom Access Token: {access_token}")
        return access_token
    
    print("Zoom API Error:", response.text)
    return None

def create_zoom_meeting(teacher_id: str, topic: str, start_time: datetime, duration: int = 60) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Creates a Zoom meeting and saves it in the database."""
    access_token = get_zoom_access_token()
    if not access_token:
        return False, "Failed to authenticate with Zoom API", None
    
    url = f"https://api.zoom.us/v2/users/{ZOOM_USER_ID}/meetings"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "topic": topic,
        "type": 2,
        "start_time": start_time.isoformat(),
        "duration": duration,
        "timezone": "UTC",
        "settings": {
            "host_video": True,
            "participant_video": True,
            "mute_upon_entry": True,
            "waiting_room": False,
            "auto_recording": "cloud"
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 201:
        meeting_data = response.json()
        
        # Save to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            meeting_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO meetings (id, teacher_id, topic, start_time, duration, join_url, start_url, zoom_meeting_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (meeting_id, teacher_id, topic, start_time, duration, 
                  meeting_data["join_url"], meeting_data["start_url"], meeting_data["id"]))
            
            conn.commit()
            meeting_data["db_meeting_id"] = meeting_id
            return True, "Meeting created successfully", meeting_data
            
        except Exception as e:
            conn.rollback()
            print(f"Database error: {str(e)}")
            return False, f"Error saving meeting: {str(e)}", None
        finally:
            conn.close()
    
    return False, f"Error creating meeting: {response.text}", None

def process_ocr(image_bytes: bytes) -> str:
    """Process OCR using web API"""
    try:
        files = {'file': ('image.jpg', image_bytes, 'image/jpeg')}
        data = {
            'apikey': OCR_CONFIG["api_key"],
            'language': 'eng',
            'isOverlayRequired': 'false',
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2',
            'isTable': 'false'
        }
        
        response = requests.post(OCR_CONFIG["url"], files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('IsErroredOnProcessing', True):
                return None
            
            extracted_text = ""
            if 'ParsedResults' in result and result['ParsedResults']:
                for parsed_result in result['ParsedResults']:
                    text = parsed_result.get('ParsedText', '')
                    if text.strip():
                        extracted_text += text + "\n"
            
            return extracted_text.strip() if extracted_text.strip() else None
        return None
        
    except Exception as e:
        print(f"OCR Error: {e}")
        return None

def extract_birthdate_and_age(text: str) -> tuple:
    """Extract birthdate from OCR text and calculate age"""
    if not text:
        return None, None
    
    date_patterns = [
        r'(?:DOB|Date\s*of\s*Birth|Birth\s*Date|Born|D\.O\.B)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        r'(?:DOB|Date\s*of\s*Birth|Birth\s*Date|Born|D\.O\.B)[:\s]*(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        r'(?:DOB|Date\s*of\s*Birth|Birth\s*Date|Born|D\.O\.B)[:\s]*(\d{1,2}\s+\w+\s+\d{4})',
        r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b',
        r'\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',
        r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})\b',
        r'(\d{1,2}\.\d{1,2}\.\d{4})',
        r'(\d{4}\.\d{1,2}\.\d{1,2})',
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2})',
        r'(\d{2}[/-]\d{1,2}[/-]\d{1,2})',
        r'(\d{1,2}\s+\d{1,2}\s+\d{4})',
        r'(\d{4}\s+\d{1,2}\s+\d{1,2})',
        r'(\d{2}-\d{2}-\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    
    for pattern in date_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            date_str = match.group(1) if match.groups() else match.group(0)
            date_str = date_str.strip()
            parsed_date = parse_date(date_str)
            if parsed_date:
                today = date.today()
                age = today.year - parsed_date.year - ((today.month, today.day) < (parsed_date.month, parsed_date.day))
                if 0 <= age <= 120:
                    return parsed_date.strftime('%Y-%m-%d'), age
    
    return None, None

def parse_date(date_str: str):
    """Enhanced date parsing function"""
    if not date_str:
        return None
        
    date_str = date_str.strip().replace('.', '/')
    
    date_formats = [
        '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y',
        '%Y/%m/%d', '%Y-%m-%d', '%d/%m/%y', '%m/%d/%y',
        '%d-%m-%y', '%m-%d-%y', '%y/%m/%d', '%y-%m-%d',
        '%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y',
        '%d-%B-%Y', '%d-%b-%Y', '%B-%d-%Y', '%b-%d-%Y',
        '%d %m %Y', '%m %d %Y', '%Y %m %d', '%Y%m%d', '%d%m%Y',
    ]
    
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt).date()
            
            if parsed_date.year < 100:
                if parsed_date.year <= 30:
                    parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                else:
                    parsed_date = parsed_date.replace(year=parsed_date.year + 1900)
            
            if 1900 <= parsed_date.year <= date.today().year:
                return parsed_date
                
        except ValueError:
            continue
    
    return None

def get_test_questions(exclude_attempted: List[int] = None) -> List[Dict]:
    """Get randomized test questions"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    questions = []
    config = TEST_CONFIG["questions_per_subject"]
    
    for subject, count in config.items():
        query = '''
            SELECT id, subject, category, question, option_a, option_b, option_c, option_d, difficulty_level
            FROM test_questions 
            WHERE subject = ?
        '''
        params = [subject]
        
        if exclude_attempted:
            placeholders = ','.join('?' * len(exclude_attempted))
            query += f' AND id NOT IN ({placeholders})'
            params.extend(exclude_attempted)
        
        query += ' ORDER BY RANDOM() LIMIT ?'
        params.append(count)
        
        cursor.execute(query, params)
        subject_questions = cursor.fetchall()
        questions.extend([dict(q) for q in subject_questions])
    
    conn.close()
    random.shuffle(questions)
    return questions

def calculate_test_result(attempt_id: str) -> Dict:
    """Calculate test result and prediction"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT tr.*, tq.subject, tq.category, tq.difficulty_level
        FROM test_responses tr
        JOIN test_questions tq ON tr.question_id = tq.id
        WHERE tr.attempt_id = ?
    ''', (attempt_id,))
    
    responses = cursor.fetchall()
    total_questions = len(responses)
    correct_answers = sum(1 for r in responses if r['is_correct'])
    wrong_answers = sum(1 for r in responses if r['selected_answer'] and not r['is_correct'])
    unanswered = sum(1 for r in responses if not r['selected_answer'])
    
    score_percentage = (correct_answers / total_questions * 100) if total_questions > 0 else 0
    
    subject_scores = {}
    for response in responses:
        subject = response['subject']
        if subject not in subject_scores:
            subject_scores[subject] = {'correct': 0, 'total': 0}
        subject_scores[subject]['total'] += 1
        if response['is_correct']:
            subject_scores[subject]['correct'] += 1
    
    result_prediction = predict_result(score_percentage, subject_scores)
    
    cursor.execute('''
        UPDATE test_attempts 
        SET end_time = CURRENT_TIMESTAMP, total_questions = ?, correct_answers = ?, 
            wrong_answers = ?, unanswered = ?, score_percentage = ?, result_status = ?
        WHERE id = ?
    ''', (total_questions, correct_answers, wrong_answers, unanswered, 
          score_percentage, result_prediction, attempt_id))
    
    conn.commit()
    conn.close()
    
    return {
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "wrong_answers": wrong_answers,
        "unanswered": unanswered,
        "score_percentage": round(score_percentage, 2),
        "result_prediction": result_prediction,
        "subject_scores": subject_scores
    }

def predict_result(score_percentage: float, subject_scores: Dict) -> str:
    """Predict test result based on score and subject performance"""
    if score_percentage >= TEST_CONFIG["passing_score"]:
        weak_subjects = 0
        for subject, scores in subject_scores.items():
            subject_percentage = (scores['correct'] / scores['total'] * 100) if scores['total'] > 0 else 0
            if subject_percentage < 50:
                weak_subjects += 1
        
        if weak_subjects <= 1:
            return "likely_pass"
        else:
            return "borderline"
    else:
        return "likely_fail"

# API Routes

@app.get("/")
async def root():
    return {
        "message": "ID Document Age Verification, Aptitude Test & Zoom Meeting System API",
        "version": "4.1.0",
        "endpoints": {
            "states": "/states - Get all available states for dropdown",
            "roles": "/roles - Get all available user roles for dropdown", 
            "register": "/register (with role selection: teacher, student, admin)",
            "admin_register": "/admin/register (deprecated - use /register with admin role)",
            "login": "/login (with role and state selection for all roles)",
            "password_reset_request": "/password-reset-request",
            "reset_password": "/reset-password",
            "validate_reset_token": "/password-reset/validate-token/{token}",
            "cleanup_expired_tokens": "/password-reset/cleanup-expired",
            "upload_document": "/upload-document",
            "student_dashboard": "/student/dashboard",
            "student_test": "/student/test",
            "teacher_dashboard": "/teacher/dashboard",
            "teacher_meetings": "/teacher/meetings",
            "admin_dashboard": "/admin/dashboard",
            "admin_users": "/admin/users",
            "admin_questions": "/admin/questions",
            "admin_test_results": "/admin/test-results",
            "admin_meetings": "/admin/meetings",
            "user_profile": "/user/profile"
        },
        "registration_requirements": {
            "admin": ["username", "email", "password", "admin_secret_key"],
            "teacher": ["username", "email", "password", "state_id", "document"],
            "student": ["username", "email", "password", "state_id", "document"]
        },
        "login_requirements": {
            "admin": ["username", "password", "role"],
            "teacher": ["username", "password", "role", "state_id"],
            "student": ["username", "password", "role", "state_id"]
        }
    }

@app.get("/states")
async def get_states():
    """Get all available states"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM states ORDER BY name")
    states = [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]
    conn.close()
    
    return {
        "success": True,
        "message": "States fetched successfully",
        "data": states
    }

@app.get("/roles")
async def get_roles():
    """Get all available user roles from database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, description, requires_document, requires_state, 
               requires_admin_key, min_age, max_age 
        FROM roles 
        ORDER BY 
            CASE id 
                WHEN 'admin' THEN 1 
                WHEN 'teacher' THEN 2 
                WHEN 'student' THEN 3 
            END
    ''')
    roles = cursor.fetchall()
    conn.close()
    
    roles_list = []
    for role in roles:
        requirements = ["username", "email", "password"]
        
        if role["requires_admin_key"]:
            requirements.append("admin_secret_key")
        if role["requires_state"]:
            requirements.append("state_id")
        if role["requires_document"]:
            requirements.append("document")
            
        age_requirement = None
        if role["min_age"] and role["max_age"]:
            age_requirement = f"Age must be between {role['min_age']} and {role['max_age']} years"
        elif role["min_age"]:
            age_requirement = f"Must be {role['min_age']} years or older"
        elif role["max_age"]:
            age_requirement = f"Must be {role['max_age']} years or younger"
        
        roles_list.append({
            "id": role["id"],
            "name": role["name"],
            "description": role["description"],
            "requirements": requirements,
            "requires_document": bool(role["requires_document"]),
            "requires_state": bool(role["requires_state"]),
            "requires_admin_key": bool(role["requires_admin_key"]),
            "age_requirement": age_requirement
        })
    
    return {
        "success": True,
        "message": "Roles fetched successfully",
        "data": roles_list
    }

# Enhanced registration endpoint with role selection (including a
# 
# 
@app.post("/register")
async def register_user_with_role(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),  # Role selection (teacher, student only)
    state_id: int = Form(...),  # Required for teacher/student
    document: UploadFile = File(...)  # Required for teacher/student
):
    """Register a new user with role selection and document verification"""
    try:
        # Validate role (admin removed since it has separate endpoint)
        if role not in ["teacher", "student"]:
            raise HTTPException(status_code=400, detail="Role must be 'teacher' or 'student'")
        
        # Get role data from database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE id = ?", (role,))
        role_data = cursor.fetchone()
        
        if not role_data:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid role selected")
        
        # Check role requirements
        if role_data["requires_document"] and not document:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Document is required for {role_data['name']} registration")
        
        if role_data["requires_state"] and not state_id:
            conn.close()
            raise HTTPException(status_code=400, detail=f"State selection is required for {role_data['name']} registration")
        
        if not document.content_type.startswith('image/'):
            conn.close()
            raise HTTPException(status_code=400, detail="Only image files are allowed")
        
        image_bytes = await document.read()
        extracted_text = process_ocr(image_bytes)
        
        if not extracted_text:
            conn.close()
            raise HTTPException(status_code=400, detail="Could not extract text from document. Please upload a clearer image.")
        
        birthdate_str, age = extract_birthdate_and_age(extracted_text)
        
        if not age:
            conn.close()
            raise HTTPException(status_code=400, detail="Could not extract age/birthdate from document")
        
        # Age validation based on role requirements from database
        if role_data["min_age"] and age < role_data["min_age"]:
            conn.close()
            raise HTTPException(status_code=400, detail=f"{role_data['name']}s must be at least {role_data['min_age']} years old")
        
        if role_data["max_age"] and age > role_data["max_age"]:
            conn.close() 
            raise HTTPException(status_code=400, detail=f"{role_data['name']}s must be {role_data['max_age']} years old or younger")
        
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user_id = generate_user_id(role)
        
        try:
            cursor.execute("SELECT name FROM states WHERE id = ?", (state_id,))
            state = cursor.fetchone()
            if not state:
                conn.close()
                raise HTTPException(status_code=400, detail="Invalid state selected")
            
            cursor.execute('''
                INSERT INTO users (id, username, email, password, role, state_id, age, birthdate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, username, email, hashed_password.decode('utf-8'), role, state_id, age, birthdate_str))
            
            doc_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO documents (id, user_id, filename, extracted_text, birthdate, age, verification_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (doc_id, user_id, document.filename, extracted_text, birthdate_str, age, "verified"))
            
            conn.commit()
            
            return {
                "success": True,
                "message": "User registered successfully",
                "data": {
                    "user_id": user_id,
                    "username": username,
                    "role": role,
                    "age": age,
                    "birthdate": birthdate_str,
                    "state": state["name"],
                    "verification_status": "verified"
                }
            }
            
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Username or email already exists")
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
@app.post("/admin/register")
async def register_admin(admin_data: AdminCreate):
    """Register a new admin user (deprecated - use /register with admin role)"""
    try:
        if admin_data.admin_secret_key != ADMIN_SECRET_KEY:
            raise HTTPException(status_code=403, detail="Invalid admin secret key")
        
        hashed_password = bcrypt.hashpw(admin_data.password.encode('utf-8'), bcrypt.gensalt())
        admin_id = generate_user_id("admin")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO users (id, username, email, password, role, state_id, age, birthdate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (admin_id, admin_data.username, admin_data.email, hashed_password.decode('utf-8'), "admin", 1, None, None))
            
            conn.commit()
            
            return {
                "success": True,
                "message": "Admin registered successfully",
                "data": {
                    "admin_id": admin_id,
                    "username": admin_data.username,
                    "email": admin_data.email,
                    "role": "admin"
                }
            }
            
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Username or email already exists")
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Admin registration failed: {str(e)}")

# Enhanced login endpoint with role and state selection (including admin)
@app.post("/login")
async def login_user_with_role(user_data: UserLoginWithRole):
    """User login endpoint with role and state selection"""
    
    # Validate role
    if user_data.role not in ["admin", "teacher", "student"]:
        raise HTTPException(status_code=400, detail="Invalid role selected")
    
    # State validation for non-admin users
    if user_data.role != "admin" and not user_data.state_id:
        raise HTTPException(status_code=400, detail="State selection is required for teachers and students")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query based on role
    if user_data.role == "admin":
        # Admin login - no state requirement
        cursor.execute('''
            SELECT u.*, s.name as state_name 
            FROM users u 
            LEFT JOIN states s ON u.state_id = s.id 
            WHERE u.username = ? AND u.role = ?
        ''', (user_data.username, user_data.role))
    else:
        # For teachers and students, also check state
        cursor.execute('''
            SELECT u.*, s.name as state_name 
            FROM users u 
            LEFT JOIN states s ON u.state_id = s.id 
            WHERE u.username = ? AND u.role = ? AND u.state_id = ?
        ''', (user_data.username, user_data.role, user_data.state_id))
    
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        if user_data.role == "admin":
            raise HTTPException(status_code=401, detail="Invalid admin credentials")
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials or role/state combination")
    
    if not bcrypt.checkpw(user_data.password.encode('utf-8'), user["password"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_access_token({"sub": user["id"], "role": user["role"]})
    
    user_response = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "age": user["age"]
    }
    
    # Add state info for non-admin users
    if user["role"] != "admin":
        user_response["state"] = user["state_name"]
        user_response["state_id"] = user["state_id"]
    
    return {
        "success": True,
        "message": "Login successful",
        "data": {
            "access_token": token,
            "token_type": "bearer",
            "user": user_response
        }
    }

# Password Reset Endpoints
@app.post("/password-reset-request", response_model=ResetTokenResponse)
async def request_password_reset(request: PasswordResetRequest):
    """Request a password reset token for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Find user by username (case-insensitive)
        cursor.execute("SELECT id, username FROM users WHERE LOWER(username) = LOWER(?)", (request.username.strip(),))
        user_data = cursor.fetchone()
        
        if not user_data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "success": False, 
                    "message": "User not found. Please check your username and try again.",
                    "error_code": "USER_NOT_FOUND"
                }
            )
        
        user_id, username = user_data["id"], user_data["username"]
        
        # Generate unique reset token
        reset_token = generate_reset_token()
        token_expires = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour
        
        # Update user with reset token
        cursor.execute(
            "UPDATE users SET reset_token = ?, reset_token_expires = ? WHERE id = ?",
            (reset_token, token_expires.isoformat(), user_id)
        )
        conn.commit()
        
        # Return the token directly (no email sending in this implementation)
        return {
            "reset_token": reset_token,
            "message": "Use this token to reset your password. This token will expire in 1 hour."
        }
        
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False, 
                "message": f"Server error occurred while processing reset request: {str(e)}",
                "error_code": "INTERNAL_SERVER_ERROR"
            }
        )
    finally:
        conn.close()

@app.post("/reset-password", response_model=ResponseModel)
async def reset_password(reset_data: PasswordReset):
    """Reset user password using a valid reset token"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Find user with the token
        cursor.execute("SELECT id, username, reset_token_expires FROM users WHERE reset_token = ?", (reset_data.token,))
        user_data = cursor.fetchone()
        
        if not user_data:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False, 
                    "message": "Invalid reset token. Please request a new password reset.",
                    "error_code": "INVALID_TOKEN"
                }
            )
        
        user_id, username, token_expires_str = user_data["id"], user_data["username"], user_data["reset_token_expires"]
        
        # Check if token is expired
        if not token_expires_str:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False, 
                    "message": "Reset token has no expiration data. Please request a new password reset.",
                    "error_code": "INVALID_TOKEN_DATA"
                }
            )
        
        try:
            token_expires = datetime.fromisoformat(token_expires_str)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False, 
                    "message": "Invalid token expiration data. Please request a new password reset.",
                    "error_code": "INVALID_TOKEN_FORMAT"
                }
            )
        
        if datetime.utcnow() > token_expires:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False, 
                    "message": "Reset token has expired. Please request a new password reset.",
                    "error_code": "TOKEN_EXPIRED"
                }
            )
        
        # Validate new password strength
        if len(reset_data.new_password) < 6:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False, 
                    "message": "New password must be at least 6 characters long",
                    "error_code": "WEAK_PASSWORD"
                }
            )
        
        # Hash the new password
        hashed_password = bcrypt.hashpw(reset_data.new_password.encode('utf-8'), bcrypt.gensalt())
        
        # Update password and clear reset token
        cursor.execute(
            "UPDATE users SET password = ?, reset_token = NULL, reset_token_expires = NULL WHERE id = ?",
            (hashed_password.decode('utf-8'), user_id)
        )
        conn.commit()
        
        return {
            "success": True,
            "message": f"Password has been reset successfully for user '{username}'",
            "data": {
                "username": username,
                "reset_time": datetime.utcnow().isoformat()
            }
        }
        
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False, 
                "message": f"Server error occurred while resetting password: {str(e)}",
                "error_code": "INTERNAL_SERVER_ERROR"
            }
        )
    finally:
        conn.close()

@app.get("/password-reset/validate-token/{token}", response_model=ResponseModel)
async def validate_reset_token(token: str):
    """Validate if a reset token is still valid (not expired)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Find user with the token
        cursor.execute("SELECT username, reset_token_expires FROM users WHERE reset_token = ?", (token,))
        user_data = cursor.fetchone()
        
        if not user_data:
            return {
                "success": False,
                "message": "Invalid reset token",
                "data": {"valid": False, "reason": "token_not_found"}
            }
        
        username, token_expires_str = user_data["username"], user_data["reset_token_expires"]
        
        if not token_expires_str:
            return {
                "success": False,
                "message": "Token has no expiration data",
                "data": {"valid": False, "reason": "invalid_token_data"}
            }
        
        try:
            token_expires = datetime.fromisoformat(token_expires_str)
        except ValueError:
            return {
                "success": False,
                "message": "Invalid token expiration format",
                "data": {"valid": False, "reason": "invalid_token_format"}
            }
        
        # Check if token is expired
        current_time = datetime.utcnow()
        if current_time > token_expires:
            return {
                "success": False,
                "message": "Reset token has expired",
                "data": {
                    "valid": False, 
                    "reason": "token_expired",
                    "expired_at": token_expires.isoformat()
                }
            }
        
        # Token is valid
        time_remaining = token_expires - current_time
        return {
            "success": True,
            "message": "Reset token is valid",
            "data": {
                "valid": True,
                "username": username,
                "expires_at": token_expires.isoformat(),
                "minutes_remaining": int(time_remaining.total_seconds() / 60)
            }
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False, 
                "message": f"Server error occurred while validating token: {str(e)}",
                "error_code": "INTERNAL_SERVER_ERROR"
            }
        )
    finally:
        conn.close()

@app.post("/password-reset/cleanup-expired", response_model=ResponseModel)
async def cleanup_expired_tokens(current_user: dict = Depends(verify_token)):
    """Admin endpoint to clean up expired reset tokens from the database"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get current time
        current_time = datetime.utcnow().isoformat()
        
        # Count expired tokens before cleanup
        cursor.execute(
            "SELECT COUNT(*) as count FROM users WHERE reset_token IS NOT NULL AND reset_token_expires < ?",
            (current_time,)
        )
        expired_count = cursor.fetchone()["count"]
        
        # Clear expired tokens
        cursor.execute(
            "UPDATE users SET reset_token = NULL, reset_token_expires = NULL WHERE reset_token IS NOT NULL AND reset_token_expires < ?",
            (current_time,)
        )
        conn.commit()
        
        return {
            "success": True,
            "message": f"Cleaned up {expired_count} expired reset tokens",
            "data": {"expired_tokens_removed": expired_count}
        }
        
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False, 
                "message": f"Error during cleanup: {str(e)}",
                "error_code": "CLEANUP_ERROR"
            }
        )
    finally:
        conn.close()

# Student Endpoints
@app.get("/admin/meetings")
async def admin_get_meetings(current_user: dict = Depends(verify_token)):
    """Admin endpoint to view all meetings"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT m.*, u.username as host_name, u.role as host_role,
               COUNT(DISTINCT mp.student_id) as participant_count,
               COUNT(DISTINCT mr.id) as recording_count
        FROM meetings m
        JOIN users u ON m.teacher_id = u.id
        LEFT JOIN meeting_participants mp ON m.id = mp.meeting_id
        LEFT JOIN meeting_recordings mr ON m.id = mr.meeting_id
        GROUP BY m.id
        ORDER BY m.start_time DESC
    ''')
    meetings = cursor.fetchall()
    
    conn.close()
    
    meetings_list = []
    for meeting in meetings:
        meetings_list.append({
            "id": meeting["id"],
            "topic": meeting["topic"],
            "host_name": meeting["host_name"],
            "host_role": meeting["host_role"],
            "start_time": meeting["start_time"],
            "duration": meeting["duration"],
            "status": meeting["status"],
            "zoom_meeting_id": meeting["zoom_meeting_id"],
            "participant_count": meeting["participant_count"],
            "recording_count": meeting["recording_count"],
            "join_url": meeting["join_url"],
            "created_at": meeting["created_at"],
            "created_by": "admin" if meeting["host_role"] == "admin" else "teacher"
        })
    
    return {
        "success": True,
        "message": "Meetings fetched successfully",
        "data": {
            "meetings": meetings_list,
            "total_count": len(meetings_list)
        }
    }
@app.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to delete a specific user and all related data"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user exists and get user details
        cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Prevent deletion of admin users
        if user["role"] == "admin":
            raise HTTPException(status_code=403, detail="Cannot delete admin users")
        
        username = user["username"]
        role = user["role"]
        
        # Delete related data in the correct order (due to foreign key constraints)
        
        # 1. Delete test responses first
        cursor.execute('''
            DELETE FROM test_responses 
            WHERE attempt_id IN (
                SELECT id FROM test_attempts WHERE user_id = ?
            )
        ''', (user_id,))
        
        # 2. Delete test attempts
        cursor.execute('DELETE FROM test_attempts WHERE user_id = ?', (user_id,))
        
        # 3. Delete meeting recordings for meetings created by this user
        if role == "teacher":
            cursor.execute('''
                DELETE FROM meeting_recordings 
                WHERE meeting_id IN (
                    SELECT id FROM meetings WHERE teacher_id = ?
                )
            ''', (user_id,))
        
        # 4. Delete meeting participants where this user was a participant
        cursor.execute('DELETE FROM meeting_participants WHERE student_id = ?', (user_id,))
        
        # 5. Delete meetings created by this user (if teacher/admin)
        if role in ["teacher", "admin"]:
            cursor.execute('DELETE FROM meetings WHERE teacher_id = ?', (user_id,))
        
        # 6. Delete documents uploaded by this user
        cursor.execute('DELETE FROM documents WHERE user_id = ?', (user_id,))
        
        # 7. Finally delete the user
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        # Check if user was actually deleted
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found or already deleted")
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"User '{username}' ({role}) and all related data deleted successfully",
            "data": {
                "deleted_user_id": user_id,
                "deleted_username": username,
                "deleted_role": role,
                "deletion_timestamp": datetime.utcnow().isoformat()
            }
        }
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")
    finally:
        conn.close()

@app.get("/student/dashboard")
async def student_dashboard(current_user: dict = Depends(verify_token)):
    """Student dashboard with test status, results, and meetings"""
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Access denied. Students only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user details
    cursor.execute('''
        SELECT u.*, s.name as state_name 
        FROM users u 
        LEFT JOIN states s ON u.state_id = s.id 
        WHERE u.id = ?
    ''', (current_user["sub"],))
    user = cursor.fetchone()
    
    # Check if test has been attempted
    cursor.execute('''
        SELECT id, start_time, end_time, total_questions, correct_answers, 
               score_percentage, result_status, admin_approval, admin_comments, approved_at
        FROM test_attempts 
        WHERE user_id = ?
    ''', (current_user["sub"],))
    test_attempt = cursor.fetchone()
    
    # Get upcoming meetings for this student (both teacher and admin created)
    cursor.execute('''
        SELECT m.id, m.topic, m.start_time, m.duration, m.join_url, m.status,
               u.username as host_name, u.role as host_role
        FROM meetings m
        JOIN meeting_participants mp ON m.id = mp.meeting_id
        JOIN users u ON m.teacher_id = u.id
        WHERE mp.student_id = ? AND m.start_time > datetime('now')
        ORDER BY m.start_time ASC
    ''', (current_user["sub"],))
    upcoming_meetings = cursor.fetchall()
    
    # Get past meetings with recordings
    cursor.execute('''
        SELECT m.id, m.topic, m.start_time, m.duration, m.status,
               u.username as host_name, u.role as host_role,
               mr.recording_url, mr.file_type
        FROM meetings m
        JOIN meeting_participants mp ON m.id = mp.meeting_id
        JOIN users u ON m.teacher_id = u.id
        LEFT JOIN meeting_recordings mr ON m.id = mr.meeting_id
        WHERE mp.student_id = ? AND m.start_time <= datetime('now')
        ORDER BY m.start_time DESC
    ''', (current_user["sub"],))
    past_meetings = cursor.fetchall()
    
    conn.close()
    
    dashboard_data = {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "state": user["state_name"],
            "age": user["age"]
        },
        "test_status": {
            "can_take_test": test_attempt is None,
            "test_completed": test_attempt is not None,
            "test_config": {
                "duration_minutes": TEST_CONFIG["duration_minutes"],
                "total_questions": TEST_CONFIG["total_questions"],
                "passing_score": TEST_CONFIG["passing_score"]
            }
        },
        "meetings": {
            "upcoming": [
                {
                    "id": meeting["id"],
                    "topic": meeting["topic"],
                    "host_name": meeting["host_name"],
                    "host_type": "Admin" if meeting["host_role"] == "admin" else "Teacher",
                    "start_time": meeting["start_time"],
                    "duration": meeting["duration"],
                    "join_url": meeting["join_url"],
                    "status": meeting["status"],
                    "time_until_meeting": "Calculate client-side",
                    "can_join": True  # Students can always see join link
                }
                for meeting in upcoming_meetings
            ],
            "past_with_recordings": [
                {
                    "id": meeting["id"],
                    "topic": meeting["topic"],
                    "host_name": meeting["host_name"],
                    "host_type": "Admin" if meeting["host_role"] == "admin" else "Teacher",
                    "start_time": meeting["start_time"],
                    "duration": meeting["duration"],
                    "status": meeting["status"],
                    "recording_url": meeting["recording_url"],
                    "file_type": meeting["file_type"],
                    "has_recording": meeting["recording_url"] is not None,
                    "embed_code": f'<iframe src="{meeting["recording_url"]}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="width: 100%; height: 400px;" sandbox="allow-same-origin allow-scripts"></iframe>' if meeting["recording_url"] else None
                }
                for meeting in past_meetings
            ]
        }
    }
    
    if test_attempt:
        dashboard_data["test_result"] = {
            "attempt_id": test_attempt["id"],
            "start_time": test_attempt["start_time"],
            "end_time": test_attempt["end_time"],
            "total_questions": test_attempt["total_questions"],
            "correct_answers": test_attempt["correct_answers"],
            "score_percentage": test_attempt["score_percentage"],
            "result_prediction": test_attempt["result_status"],
            "admin_approval": test_attempt["admin_approval"],
            "admin_comments": test_attempt["admin_comments"],
            "approved_at": test_attempt["approved_at"],
            "final_status": "Pending Admin Review" if test_attempt["admin_approval"] == "pending" else 
                           ("PASSED" if test_attempt["admin_approval"] == "approved" else "FAILED")
        }
    
    return {
        "success": True,
        "message": "Student dashboard loaded successfully",
        "data": dashboard_data
    }

@app.get("/student/test")
async def start_student_test(current_user: dict = Depends(verify_token)):
    """Get aptitude test questions for student"""
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Access denied. Students only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM test_attempts WHERE user_id = ?', (current_user["sub"],))
    existing_attempt = cursor.fetchone()
    
    if existing_attempt:
        conn.close()
        raise HTTPException(status_code=400, detail="You have already taken the aptitude test. You can only take it once.")
    
    test_session_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    
    # Call the UTILITY function (not the endpoint)
    questions = get_test_questions()  # This calls the utility function
    
    if len(questions) < TEST_CONFIG["total_questions"]:
        conn.close()
        raise HTTPException(status_code=500, detail="Insufficient questions available for the test.")
    
    cursor.execute('''
        INSERT INTO test_attempts (id, user_id, test_session_id, total_questions)
        VALUES (?, ?, ?, ?)
    ''', (attempt_id, current_user["sub"], test_session_id, len(questions)))
    
    for question in questions:
        response_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO test_responses (id, attempt_id, question_id)
            VALUES (?, ?, ?)
        ''', (response_id, attempt_id, question["id"]))
    
    conn.commit()
    conn.close()
    
    # Remove correct answers before sending to frontend
    for question in questions:
        question.pop('correct_answer', None)
    
    return {
        "success": True,
        "message": "Test questions loaded successfully",
        "data": {
            "attempt_id": attempt_id,
            "test_session_id": test_session_id,
            "duration_minutes": TEST_CONFIG["duration_minutes"],
            "total_questions": len(questions),
            "questions": questions,
            "instructions": [
                "You have 60 minutes to complete the test",
                "There are 30 questions covering various subjects",
                "Each question has only one correct answer",
                "You can only take this test ONCE",
                "Your result will be reviewed by admin",
                "Click 'Submit Test' when finished"
            ]
        }
    }
@app.post("/student/test/submit")
async def submit_test(
    test_data: TestSubmission,
    current_user: dict = Depends(verify_token)
):
    """Submit aptitude test answers"""
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Access denied. Students only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id FROM test_attempts 
        WHERE user_id = ? AND end_time IS NULL
        ORDER BY start_time DESC LIMIT 1
    ''', (current_user["sub"],))
    attempt = cursor.fetchone()
    
    if not attempt:
        raise HTTPException(status_code=400, detail="No active test session found.")
    
    attempt_id = attempt["id"]
    
    for answer in test_data.answers:
        cursor.execute('''
            SELECT correct_answer FROM test_questions WHERE id = ?
        ''', (answer.question_id,))
        question = cursor.fetchone()
        
        if question:
            is_correct = answer.selected_answer.upper() == question["correct_answer"].upper()
            
            cursor.execute('''
                UPDATE test_responses 
                SET selected_answer = ?, is_correct = ?, time_taken = ?
                WHERE attempt_id = ? AND question_id = ?
            ''', (answer.selected_answer, is_correct, answer.time_taken, attempt_id, answer.question_id))
    
    conn.commit()
    
    result = calculate_test_result(attempt_id)
    
    conn.close()
    
    return {
        "success": True,
        "message": "Test submitted successfully",
        "data": {
            "attempt_id": attempt_id,
            "result": result,
            "message": "Your test has been submitted and is under admin review. Results will be available once approved."
        }
    }

# Teacher Endpoints
@app.get("/teacher/dashboard")
async def teacher_dashboard(current_user: dict = Depends(verify_token)):
    """Teacher dashboard with meetings and students"""
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get teacher details
    cursor.execute('''
        SELECT u.*, s.name as state_name 
        FROM users u 
        LEFT JOIN states s ON u.state_id = s.id 
        WHERE u.id = ?
    ''', (current_user["sub"],))
    teacher = cursor.fetchone()
    
    # Get all students for meeting invitations
    cursor.execute('''
        SELECT u.id, u.username, u.email, s.name as state_name
        FROM users u
        LEFT JOIN states s ON u.state_id = s.id
        WHERE u.role = 'student'
        ORDER BY u.username
    ''', )
    students = cursor.fetchall()
    
    # Get teacher's meetings
    cursor.execute('''
        SELECT id, topic, start_time, duration, join_url, start_url, status, zoom_meeting_id
        FROM meetings 
        WHERE teacher_id = ?
        ORDER BY start_time DESC
    ''', (current_user["sub"],))
    meetings = cursor.fetchall()
    
    conn.close()
    
    dashboard_data = {
        "teacher": {
            "id": teacher["id"],
            "username": teacher["username"],
            "email": teacher["email"],
            "state": teacher["state_name"],
            "age": teacher["age"]
        },
        "students": [
            {
                "id": student["id"],
                "username": student["username"],
                "email": student["email"],
                "state": student["state_name"]
            }
            for student in students
        ],
        "meetings": [
            {
                "id": meeting["id"],
                "topic": meeting["topic"],
                "start_time": meeting["start_time"],
                "duration": meeting["duration"],
                "join_url": meeting["join_url"],
                "start_url": meeting["start_url"],
                "status": meeting["status"],
                "zoom_meeting_id": meeting["zoom_meeting_id"]
            }
            for meeting in meetings
        ]
    }
    
    return {
        "success": True,
        "message": "Teacher dashboard loaded successfully",
        "data": dashboard_data
    }

@app.post("/teacher/meetings")
async def create_meeting(
    meeting_data: MeetingCreate,
    current_user: dict = Depends(verify_token)
):
    """Create a new Zoom meeting and invite students"""
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    try:
        # Create Zoom meeting
        success, message, zoom_data = create_zoom_meeting(
            current_user["sub"],
            meeting_data.topic,
            meeting_data.start_time,
            meeting_data.duration
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        meeting_id = zoom_data["db_meeting_id"]
        
        # Add participants
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for student_id in meeting_data.student_ids:
            participant_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO meeting_participants (id, meeting_id, student_id)
                VALUES (?, ?, ?)
            ''', (participant_id, meeting_id, student_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": "Meeting created and students invited successfully",
            "data": {
                "meeting_id": meeting_id,
                "zoom_meeting_id": zoom_data["id"],
                "topic": meeting_data.topic,
                "start_time": meeting_data.start_time.isoformat(),
                "join_url": zoom_data["join_url"],
                "start_url": zoom_data["start_url"],
                "invited_students": len(meeting_data.student_ids)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create meeting: {str(e)}")

@app.get("/teacher/meetings/{meeting_id}/participants")
async def get_meeting_participants(
    meeting_id: str,
    current_user: dict = Depends(verify_token)
):
    """Get participants for a specific meeting"""
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify meeting belongs to teacher
    cursor.execute('''
        SELECT id FROM meetings WHERE id = ? AND teacher_id = ?
    ''', (meeting_id, current_user["sub"]))
    meeting = cursor.fetchone()
    
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Get participants
    cursor.execute('''
        SELECT mp.id, mp.joined_at, u.username, u.email
        FROM meeting_participants mp
        JOIN users u ON mp.student_id = u.id
        WHERE mp.meeting_id = ?
        ORDER BY u.username
    ''', (meeting_id,))
    participants = cursor.fetchall()
    
    conn.close()
    
    return {
        "success": True,
        "message": "Meeting participants retrieved successfully",
        "data": {
            "meeting_id": meeting_id,
            "participants": [
                {
                    "id": p["id"],
                    "username": p["username"],
                    "email": p["email"],
                    "joined_at": p["joined_at"]
                }
                for p in participants
            ],
            "total_participants": len(participants)
        }
    }

@app.post("/teacher/meetings/{meeting_id}/fetch-recordings")
async def fetch_meeting_recordings(
    meeting_id: str,
    current_user: dict = Depends(verify_token)
):
    """Fetch and save recordings for a completed meeting"""
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get meeting details
    cursor.execute('''
        SELECT zoom_meeting_id FROM meetings 
        WHERE id = ? AND teacher_id = ?
    ''', (meeting_id, current_user["sub"]))
    meeting = cursor.fetchone()
    
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    zoom_meeting_id = meeting["zoom_meeting_id"]
    
    # Get Zoom access token
    access_token = get_zoom_access_token()
    if not access_token:
        raise HTTPException(status_code=400, detail="Zoom authentication failed")
    
    # Fetch recordings from Zoom
    url = f"https://api.zoom.us/v2/meetings/{zoom_meeting_id}/recordings"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Zoom API error: {response.text}")
    
    recording_data = response.json()
    recording_files = recording_data.get("recording_files", [])
    
    recordings_added = 0
    for rec_file in recording_files:
        if rec_file.get("file_type") == "MP4":
            # Check if recording already exists
            cursor.execute('''
                SELECT id FROM meeting_recordings 
                WHERE meeting_id = ? AND recording_url = ?
            ''', (meeting_id, rec_file.get("play_url")))
            existing = cursor.fetchone()
            
            if not existing:
                recording_id = str(uuid.uuid4())
                cursor.execute('''
                    INSERT INTO meeting_recordings 
                    (id, meeting_id, recording_url, file_type, file_size, duration)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (recording_id, meeting_id, rec_file.get("play_url"), 
                      rec_file.get("file_type"), rec_file.get("file_size"), 
                      rec_file.get("recording_start")))
                recordings_added += 1
    
    if recordings_added > 0:
        conn.commit()
    
    conn.close()
    
    return {
        "success": True,
        "message": f"Added {recordings_added} new recordings" if recordings_added > 0 else "No new recordings found",
        "data": {"recordings_added": recordings_added}
    }

# Admin Endpoints
@app.get("/admin/dashboard")
async def admin_dashboard(current_user: dict = Depends(verify_token)):
    """Admin dashboard - overview statistics"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'teacher'")
    teacher_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'student'")
    student_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM documents")
    document_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM documents WHERE verification_status = 'verified'")
    verified_count = cursor.fetchone()["total"]
    
    cursor.execute('''
        SELECT COUNT(*) as total FROM users 
        WHERE role != 'admin' AND created_at >= datetime('now', '-7 days')
    ''')
    recent_registrations = cursor.fetchone()["total"]
    
    # Test statistics
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts")
    total_tests = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'pending'")
    pending_reviews = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'approved'")
    approved_tests = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'rejected'")
    rejected_tests = cursor.fetchone()["total"]
    
    # Meeting statistics
    cursor.execute("SELECT COUNT(*) as total FROM meetings")
    total_meetings = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM meetings WHERE start_time > datetime('now')")
    upcoming_meetings = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM meeting_recordings")
    total_recordings = cursor.fetchone()["total"]
    
    conn.close()
    
    return {
        "success": True,
        "message": "Dashboard data fetched successfully",
        "data": {
            "statistics": {
                "total_teachers": teacher_count,
                "total_students": student_count,
                "total_documents": document_count,
                "verified_documents": verified_count,
                "recent_registrations": recent_registrations,
                "total_tests_taken": total_tests,
                "pending_test_reviews": pending_reviews,
                "approved_tests": approved_tests,
                "rejected_tests": rejected_tests,
                "total_meetings": total_meetings,
                "upcoming_meetings": upcoming_meetings,
                "total_recordings": total_recordings
            }
        }
    }

@app.get("/admin/users")
async def admin_get_users(
    role: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to get all users with optional role filter"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if role and role in ["teacher", "student"]:
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.role, u.age, u.birthdate, u.created_at, s.name as state_name
            FROM users u 
            LEFT JOIN states s ON u.state_id = s.id 
            WHERE u.role = ?
            ORDER BY u.created_at DESC
        ''', (role,))
    else:
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.role, u.age, u.birthdate, u.created_at, s.name as state_name
            FROM users u 
            LEFT JOIN states s ON u.state_id = s.id 
            WHERE u.role != 'admin'
            ORDER BY u.created_at DESC
        ''')
    
    users = cursor.fetchall()
    conn.close()
    
    users_list = []
    for user in users:
        users_list.append({
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "state": user["state_name"],
            "age": user["age"],
            "birthdate": user["birthdate"],
            "created_at": user["created_at"]
        })
    
    return {
        "success": True,
        "message": f"{'All users' if not role else role.title() + 's'} fetched successfully",
        "data": {
            "users": users_list,
            "total_count": len(users_list)
        }
    }

@app.get("/admin/users/{user_id}")
async def admin_get_user_details(
    user_id: str,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to get specific user details"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.*, s.name as state_name 
        FROM users u 
        LEFT JOIN states s ON u.state_id = s.id 
        WHERE u.id = ?
    ''', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    cursor.execute('''
        SELECT id, filename, extracted_text, birthdate, age, verification_status, created_at
        FROM documents 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,))
    documents = cursor.fetchall()
    
    conn.close()
    
    return {
        "success": True,
        "message": "User details fetched successfully",
        "data": {
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
                "state": user["state_name"],
                "age": user["age"],
                "birthdate": user["birthdate"],
                "created_at": user["created_at"]
            },
            "documents": [dict(doc) for doc in documents]
        }
    }

@app.get("/admin/questions")
async def admin_get_questions(
    subject: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to view all test questions"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if subject:
        cursor.execute('''
            SELECT id, subject, category, question, option_a, option_b, option_c, option_d, 
                   correct_answer, difficulty_level, grade_level
            FROM test_questions 
            WHERE subject = ?
            ORDER BY subject, category, difficulty_level
        ''', (subject,))
    else:
        cursor.execute('''
            SELECT id, subject, category, question, option_a, option_b, option_c, option_d, 
                   correct_answer, difficulty_level, grade_level
            FROM test_questions 
            ORDER BY subject, category, difficulty_level
        ''')
    
    questions = cursor.fetchall()
    conn.close()
    
    questions_list = []
    for q in questions:
        questions_list.append({
            "id": q["id"],
            "subject": q["subject"],
            "category": q["category"],
            "question": q["question"],
            "options": {
                "A": q["option_a"],
                "B": q["option_b"],
                "C": q["option_c"],
                "D": q["option_d"]
            },
            "correct_answer": q["correct_answer"],
            "difficulty_level": q["difficulty_level"],
            "grade_level": q["grade_level"]
        })
    
    # Group by subject for better organization
    questions_by_subject = {}
    for q in questions_list:
        subject = q["subject"]
        if subject not in questions_by_subject:
            questions_by_subject[subject] = []
        questions_by_subject[subject].append(q)
    
    return {
        "success": True,
        "message": f"Questions fetched successfully{' for ' + subject if subject else ''}",
        "data": {
            "questions_by_subject": questions_by_subject,
            "all_questions": questions_list,
            "total_count": len(questions_list),
            "subjects_available": list(questions_by_subject.keys())
        }
    }

@app.get("/admin/test-results")
async def admin_get_test_results(
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to view all test results"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT ta.*, u.username, u.email, s.name as state_name
        FROM test_attempts ta
        JOIN users u ON ta.user_id = u.id
        LEFT JOIN states s ON u.state_id = s.id
        WHERE u.role = 'student'
    '''
    params = []
    
    if status and status in ["pending", "approved", "rejected"]:
        query += ' AND ta.admin_approval = ?'
        params.append(status)
    
    query += ' ORDER BY ta.start_time DESC'
    
    cursor.execute(query, params)
    test_results = cursor.fetchall()
    
    conn.close()
    
    results_list = []
    for result in test_results:
        results_list.append({
            "attempt_id": result["id"],
            "student": {
                "id": result["user_id"],
                "username": result["username"],
                "email": result["email"],
                "state": result["state_name"]
            },
            "test_details": {
                "start_time": result["start_time"],
                "end_time": result["end_time"],
                "total_questions": result["total_questions"],
                "correct_answers": result["correct_answers"],
                "wrong_answers": result["wrong_answers"],
                "unanswered": result["unanswered"],
                "score_percentage": result["score_percentage"],
                "result_prediction": result["result_status"]
            },
            "admin_review": {
                "approval_status": result["admin_approval"],
                "comments": result["admin_comments"],
                "approved_by": result["approved_by"],
                "approved_at": result["approved_at"]
            }
        })
    
    return {
        "success": True,
        "message": f"Test results fetched successfully",
        "data": {
            "test_results": results_list,
            "total_count": len(results_list),
            "filter_applied": status or "all"
        }
    }

@app.post("/admin/test-results/{attempt_id}/approve")
async def admin_approve_test(
    attempt_id: str,
    approval_data: AdminApproval,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to approve/reject test results"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    if approval_data.result_status not in ["approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Result status must be 'approved' or 'rejected'")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, user_id FROM test_attempts WHERE id = ?', (attempt_id,))
    attempt = cursor.fetchone()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Test attempt not found")
    
    cursor.execute('''
        UPDATE test_attempts 
        SET admin_approval = ?, admin_comments = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (approval_data.result_status, approval_data.comments, current_user["sub"], attempt_id))
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": f"Test result {approval_data.result_status} successfully",
        "data": {
            "attempt_id": attempt_id,
            "approval_status": approval_data.result_status,
            "comments": approval_data.comments,
            "approved_by": current_user["sub"]
        }
    }

@app.post("/admin/meetings")
async def admin_create_meeting(
    meeting_data: MeetingCreate,
    current_user: dict = Depends(verify_token)
):
    """Admin creates a new Zoom meeting and invites students"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    try:
        # For admin-created meetings, we need to assign a teacher or use admin as host
        # Let's create a special admin meeting format
        success, message, zoom_data = create_zoom_meeting(
            current_user["sub"],  # Admin as meeting host
            meeting_data.topic,
            meeting_data.start_time,
            meeting_data.duration
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        meeting_id = zoom_data["db_meeting_id"]
        
        # Add participants
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for student_id in meeting_data.student_ids:
            participant_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO meeting_participants (id, meeting_id, student_id)
                VALUES (?, ?, ?)
            ''', (participant_id, meeting_id, student_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": "Admin meeting created and students invited successfully",
            "data": {
                "meeting_id": meeting_id,
                "zoom_meeting_id": zoom_data["id"],
                "topic": meeting_data.topic,
                "start_time": meeting_data.start_time.isoformat(),
                "join_url": zoom_data["join_url"],
                "start_url": zoom_data["start_url"],
                "invited_students": len(meeting_data.student_ids),
                "created_by": "admin"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create admin meeting: {str(e)}")

@app.get("/admin/students/active")
async def admin_get_active_students(current_user: dict = Depends(verify_token)):
    """Admin endpoint to get all students who have logged in recently"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all students - we can track last login by checking test attempts or just show all registered students
    cursor.execute('''
        SELECT u.id, u.username, u.email, u.age, u.created_at, s.name as state_name,
               ta.start_time as last_test_attempt
        FROM users u
        LEFT JOIN states s ON u.state_id = s.id
        LEFT JOIN test_attempts ta ON u.id = ta.user_id
        WHERE u.role = 'student'
        ORDER BY u.created_at DESC
    ''')
    students = cursor.fetchall()
    
    conn.close()
    
    students_list = []
    for student in students:
        students_list.append({
            "id": student["id"],
            "username": student["username"],
            "email": student["email"],
            "age": student["age"],
            "state": student["state_name"],
            "registered_at": student["created_at"],
            "last_activity": student["last_test_attempt"] or student["created_at"],
            "has_taken_test": student["last_test_attempt"] is not None
        })
    
    return {
        "success": True,
        "message": "Active students fetched successfully",
        "data": {
            "students": students_list,
            "total_count": len(students_list)
        }
    }

@app.get("/admin/dashboard")
async def admin_dashboard(current_user: dict = Depends(verify_token)):
    """Admin dashboard - overview statistics"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'teacher'")
    teacher_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'student'")
    student_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM documents")
    document_count = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM documents WHERE verification_status = 'verified'")
    verified_count = cursor.fetchone()["total"]
    
    cursor.execute('''
        SELECT COUNT(*) as total FROM users 
        WHERE role != 'admin' AND created_at >= datetime('now', '-7 days')
    ''')
    recent_registrations = cursor.fetchone()["total"]
    
    # Test statistics
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts")
    total_tests = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'pending'")
    pending_reviews = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'approved'")
    approved_tests = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM test_attempts WHERE admin_approval = 'rejected'")
    rejected_tests = cursor.fetchone()["total"]
    
    # Meeting statistics
    cursor.execute("SELECT COUNT(*) as total FROM meetings")
    total_meetings = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM meetings WHERE start_time > datetime('now')")
    upcoming_meetings = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as total FROM meeting_recordings")
    total_recordings = cursor.fetchone()["total"]
    
    # Get recent students for quick meeting creation
    cursor.execute('''
        SELECT u.id, u.username, u.email, s.name as state_name
        FROM users u
        LEFT JOIN states s ON u.state_id = s.id
        WHERE u.role = 'student'
        ORDER BY u.created_at DESC
        LIMIT 10
    ''')
    recent_students = cursor.fetchall()
    
    conn.close()
    
    return {
        "success": True,
        "message": "Dashboard data fetched successfully",
        "data": {
            "statistics": {
                "total_teachers": teacher_count,
                "total_students": student_count,
                "total_documents": document_count,
                "verified_documents": verified_count,
                "recent_registrations": recent_registrations,
                "total_tests_taken": total_tests,
                "pending_test_reviews": pending_reviews,
                "approved_tests": approved_tests,
                "rejected_tests": rejected_tests,
                "total_meetings": total_meetings,
                "upcoming_meetings": upcoming_meetings,
                "total_recordings": total_recordings
            },
            "quick_actions": {
                "recent_students": [
                    {
                        "id": student["id"],
                        "username": student["username"],
                        "email": student["email"],
                        "state": student["state_name"]
                    }
                    for student in recent_students
                ]
            }
        }
    }

@app.delete("/admin/test-results/clear")
async def admin_clear_old_test_results(
    days_old: int = 30,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to clear old test results"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count FROM test_attempts 
        WHERE start_time < datetime('now', '-' || ? || ' days')
    ''', (days_old,))
    count_to_delete = cursor.fetchone()["count"]
    
    if count_to_delete == 0:
        conn.close()
        return {
            "success": True,
            "message": f"No test results older than {days_old} days found",
            "data": {"deleted_count": 0}
        }
    
    cursor.execute('''
        SELECT id FROM test_attempts 
        WHERE start_time < datetime('now', '-' || ? || ' days')
    ''', (days_old,))
    attempt_ids = [row["id"] for row in cursor.fetchall()]
    
    if attempt_ids:
        placeholders = ','.join('?' * len(attempt_ids))
        cursor.execute(f'DELETE FROM test_responses WHERE attempt_id IN ({placeholders})', attempt_ids)
        cursor.execute(f'DELETE FROM test_attempts WHERE id IN ({placeholders})', attempt_ids)
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": f"Successfully cleared {count_to_delete} old test results",
        "data": {
            "deleted_count": count_to_delete,
            "days_threshold": days_old
        }
    }

@app.delete("/admin/meetings/clear")
async def admin_clear_old_meetings(
    days_old: int = 90,
    current_user: dict = Depends(verify_token)
):
    """Admin endpoint to clear old meetings"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count FROM meetings 
        WHERE start_time < datetime('now', '-' || ? || ' days')
    ''', (days_old,))
    count_to_delete = cursor.fetchone()["count"]
    
    if count_to_delete == 0:
        conn.close()
        return {
            "success": True,
            "message": f"No meetings older than {days_old} days found",
            "data": {"deleted_count": 0}
        }
    
    cursor.execute('''
        SELECT id FROM meetings 
        WHERE start_time < datetime('now', '-' || ? || ' days')
    ''', (days_old,))
    meeting_ids = [row["id"] for row in cursor.fetchall()]
    
    if meeting_ids:
        placeholders = ','.join('?' * len(meeting_ids))
        cursor.execute(f'DELETE FROM meeting_recordings WHERE meeting_id IN ({placeholders})', meeting_ids)
        cursor.execute(f'DELETE FROM meeting_participants WHERE meeting_id IN ({placeholders})', meeting_ids)
        cursor.execute(f'DELETE FROM meetings WHERE id IN ({placeholders})', meeting_ids)
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": f"Successfully cleared {count_to_delete} old meetings",
        "data": {
            "deleted_count": count_to_delete,
            "days_threshold": days_old
        }
    }

# General Endpoints
@app.post("/upload-document")
async def upload_document(
    document: UploadFile = File(...),
    current_user: dict = Depends(verify_token)
):
    """Upload and process ID document for logged-in user"""
    try:
        if not document.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Only image files are allowed")
        
        image_bytes = await document.read()
        extracted_text = process_ocr(image_bytes)
        
        if not extracted_text:
            raise HTTPException(status_code=400, detail="Could not extract text from document")
        
        birthdate_str, age = extract_birthdate_and_age(extracted_text)
        
        doc_id = str(uuid.uuid4())
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO documents (id, user_id, filename, extracted_text, birthdate, age, verification_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, current_user["sub"], document.filename, extracted_text, birthdate_str, age, "verified" if age else "failed"))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": "Document processed successfully",
            "data": {
                "document_id": doc_id,
                "filename": document.filename,
                "extracted_text": extracted_text,
                "birthdate": birthdate_str,
                "age": age,
                "verification_status": "verified" if age else "failed"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document processing failed: {str(e)}")

@app.get("/user/profile")
async def get_user_profile(current_user: dict = Depends(verify_token)):
    """Get current user profile"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.*, s.name as state_name 
        FROM users u 
        LEFT JOIN states s ON u.state_id = s.id 
        WHERE u.id = ?
    ''', (current_user["sub"],))
    user = cursor.fetchone()
    
    cursor.execute('''
        SELECT id, filename, birthdate, age, verification_status, created_at
        FROM documents 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (current_user["sub"],))
    documents = cursor.fetchall()
    
    conn.close()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "success": True,
        "message": "Profile fetched successfully",
        "data": {
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
                "state": user["state_name"],
                "age": user["age"],
                "birthdate": user["birthdate"],
                "created_at": user["created_at"]
            },
            "documents": [dict(doc) for doc in documents]
        }
    }

# Zoom Webhook Endpoints
@app.post("/webhook/recording-completed")
async def recording_completed_webhook(payload: dict):
    """Webhook receiver for when Zoom recordings are completed"""
    event = payload.get("event")
    if event != "recording.completed":
        return {"message": "Event ignored"}
    
    meeting_id = payload.get("payload", {}).get("object", {}).get("id")
    if meeting_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Find the meeting in our database
            cursor.execute('SELECT id FROM meetings WHERE zoom_meeting_id = ?', (meeting_id,))
            meeting = cursor.fetchone()
            
            if meeting:
                # Get recordings from Zoom
                access_token = get_zoom_access_token()
                if access_token:
                    url = f"https://api.zoom.us/v2/meetings/{meeting_id}/recordings"
                    headers = {"Authorization": f"Bearer {access_token}"}
                    
                    response = requests.get(url, headers=headers)
                    if response.status_code == 200:
                        recording_data = response.json()
                        recording_files = recording_data.get("recording_files", [])
                        
                        for rec_file in recording_files:
                            if rec_file.get("file_type") == "MP4":
                                # Check if recording already exists
                                cursor.execute('''
                                    SELECT id FROM meeting_recordings 
                                    WHERE meeting_id = ? AND recording_url = ?
                                ''', (meeting["id"], rec_file.get("play_url")))
                                existing = cursor.fetchone()
                                
                                if not existing:
                                    recording_id = str(uuid.uuid4())
                                    cursor.execute('''
                                        INSERT INTO meeting_recordings 
                                        (id, meeting_id, recording_url, file_type, file_size, duration)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (recording_id, meeting["id"], rec_file.get("play_url"),
                                          rec_file.get("file_type"), rec_file.get("file_size"),
                                          rec_file.get("recording_start")))
                        
                        conn.commit()
                        return {"success": True, "message": "Recordings saved"}
            
            return {"success": False, "message": "Meeting not found or couldn't save recordings"}
        except Exception as e:
            print(f"Webhook error: {str(e)}")
            return {"success": False, "message": f"Error processing webhook: {str(e)}"}
        finally:
            conn.close()
    
    return {"success": False, "message": "Invalid payload"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)