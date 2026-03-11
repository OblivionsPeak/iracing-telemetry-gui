import sqlite3
import os
import json
from datetime import datetime

class HistoryManager:
    def __init__(self, db_path="telemetry_history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                car_name TEXT,
                track_name TEXT,
                date TEXT,
                setup_yaml TEXT
            )
        ''')
        
        # Create laps table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                lap_number INTEGER,
                lap_time REAL,
                is_flying BOOLEAN,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')
        
        conn.commit()
        conn.close()

    def save_session(self, file_path, session_info, laps):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Extract metadata from session_info
        driver_info = session_info.get('DriverInfo', {})
        driver_idx = driver_info.get('DriverCarIdx', 0)
        drivers = driver_info.get('Drivers', [])
        
        car_name = "Unknown Car"
        if drivers and driver_idx < len(drivers):
            car_name = drivers[driver_idx].get('CarScreenName', "Unknown Car")
            
        track_info = session_info.get('WeekendInfo', {})
        track_name = track_info.get('TrackDisplayName', "Unknown Track")
        
        # Date can be current time if not in metadata or format it
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Setup YAML - we can store the whole CarSetup section if it exists
        car_setup = session_info.get('CarSetup', {})
        setup_yaml = json.dumps(car_setup) # Storing as JSON string for simplicity if it's a dict
        
        cursor.execute('''
            INSERT INTO sessions (file_path, car_name, track_name, date, setup_yaml)
            VALUES (?, ?, ?, ?, ?)
        ''', (file_path, car_name, track_name, date_str, setup_yaml))
        
        session_id = cursor.lastrowid
        
        for lap in laps:
            cursor.execute('''
                INSERT INTO laps (session_id, lap_number, lap_time, is_flying)
                VALUES (?, ?, ?, ?)
            ''', (session_id, lap.lap_number, lap.lap_time, lap.is_flying))
            
        conn.commit()
        conn.close()
        return session_id

    def get_all_sessions(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions ORDER BY id DESC')
        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return sessions

    def get_session(self, session_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
        session = dict(cursor.fetchone())
        conn.close()
        return session

    def get_laps(self, session_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM laps WHERE session_id = ?', (session_id,))
        laps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return laps

    def get_best_lap(self, car_name, track_name):
        """Returns the best lap (fastest is_flying) for a specific car and track."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Join sessions and laps to find the fastest flying lap
        query = '''
            SELECT sessions.file_path, laps.lap_number, laps.lap_time
            FROM laps
            JOIN sessions ON sessions.id = laps.session_id
            WHERE sessions.car_name = ? AND sessions.track_name = ? AND laps.is_flying = 1
            ORDER BY laps.lap_time ASC
            LIMIT 1
        '''
        cursor.execute(query, (car_name, track_name))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
