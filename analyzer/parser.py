import os
import pandas as pd
import irsdk
import yaml

class Lap:
    """Represents a single lap in the telemetry session."""
    def __init__(self, lap_number, start_index, end_index, lap_time, is_flying=False):
        self.lap_number = lap_number
        self.start_index = start_index
        self.end_index = end_index
        self.lap_time = lap_time
        self.is_flying = is_flying

    def __repr__(self):
        return f"Lap({self.lap_number}, flying={self.is_flying}, time={self.lap_time:.3f}s)"

class TelemetryParser:
    def __init__(self):
        self.ibt = irsdk.IBT()
        self.file_path = None
        self.session_info = None
        self.var_names = []
        self.laps = []

    def load_file(self, file_path: str):
        """
        Loads an .ibt file's metadata and segments it into laps.
        Implements lazy loading by only extracting session info and lap headers.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        self.file_path = file_path
        
        # Open the IBT file
        self.ibt.open(self.file_path)
        
        # Check if it opened correctly
        if not hasattr(self.ibt, '_header') or self.ibt._header is None:
            return [], {}
            
        # Extract Session Info (YAML)
        try:
            header = self.ibt._header
            start = header.session_info_offset
            length = header.session_info_len
            # irsdk uses cp1252 for yaml data
            yaml_data = self.ibt._shared_mem[start : start + length].rstrip(b'\x00').decode('cp1252')
            self.session_info = yaml.safe_load(yaml_data)
        except Exception:
            self.session_info = {}

        # Store available telemetry variable names
        self.var_names = self.ibt.var_headers_names
        
        # Segment the session into laps
        self._segment_laps()
        
        self.ibt.close()
        return self.laps, self.session_info

    def _segment_laps(self):
        """
        Identifies lap boundaries and detects 'Flying Laps'.
        A flying lap is one where 'LapCompleted' has incremented and the car did not 
        enter or exit the pits during that lap.
        """
        if 'Lap' not in self.var_names or 'SessionTime' not in self.var_names:
            self.laps = []
            return

        # Load only the minimal channels needed for segmentation
        laps_raw = self.ibt.get_all('Lap')
        times_raw = self.ibt.get_all('SessionTime')
        
        if not laps_raw or not times_raw:
            self.laps = []
            return

        # Optional channels for flying lap detection
        lap_completed_raw = self.ibt.get_all('LapCompleted') if 'LapCompleted' in self.var_names else None
        
        # Pit road detection logic
        on_pit_road = None
        player_idx = self.session_info.get('DriverInfo', {}).get('DriverCarIdx', 0)
        
        if 'CarIdxOnPitRoad' in self.var_names:
            pit_road_all = self.ibt.get_all('CarIdxOnPitRoad')
            # Extract player's pit status from the array (if player_idx is valid)
            try:
                on_pit_road = [samples[player_idx] for samples in pit_road_all]
            except (IndexError, TypeError):
                on_pit_road = None
        elif 'PlayerCarInPitStall' in self.var_names:
            on_pit_road = self.ibt.get_all('PlayerCarInPitStall')

        self.laps = []
        start_idx = 0
        current_lap_val = laps_raw[0]

        for i in range(1, len(laps_raw)):
            if laps_raw[i] != current_lap_val:
                # End of previous lap detected
                end_idx = i - 1
                
                # Calculate lap time using the time at the transition point
                lap_time = times_raw[i] - times_raw[start_idx]
                
                is_flying = True
                
                # Rule: LapCompleted must increment to be a full flying lap
                if lap_completed_raw is not None:
                    if lap_completed_raw[i] <= lap_completed_raw[start_idx]:
                        is_flying = False
                
                # Rule: Must not be on pit road during the lap
                if on_pit_road is not None:
                    if any(on_pit_road[start_idx:i]):
                        is_flying = False
                
                self.laps.append(Lap(
                    lap_number=int(current_lap_val),
                    start_index=start_idx,
                    end_index=end_idx,
                    lap_time=float(lap_time),
                    is_flying=is_flying
                ))
                
                start_idx = i
                current_lap_val = laps_raw[i]

        # Handle the final incomplete lap in the file
        if start_idx < len(laps_raw):
            end_idx = len(laps_raw) - 1
            lap_time = times_raw[end_idx] - times_raw[start_idx]
            self.laps.append(Lap(
                lap_number=int(current_lap_val),
                start_index=start_idx,
                end_index=end_idx,
                lap_time=float(lap_time),
                is_flying=False
            ))

    def get_lap_data(self, lap_number, channels):
        """
        Extracts only the specified channels for a specific lap number.
        Returns a pandas DataFrame.
        """
        target_lap = next((l for l in self.laps if l.lap_number == lap_number), None)
        if not target_lap:
            return pd.DataFrame()

        # Re-open the IBT file to read the requested channels
        self.ibt.open(self.file_path)
        try:
            data = {}
            for chan in channels:
                if chan in self.var_names:
                    all_data = self.ibt.get_all(chan)
                    if all_data:
                        # Slice the data for the specific lap's index range
                        data[chan] = all_data[target_lap.start_index : target_lap.end_index + 1]
            return pd.DataFrame(data)
        except Exception as e:
            # In a production environment, this should be logged
            return pd.DataFrame()
        finally:
            self.ibt.close()

    def get_channels(self):
        """Returns a list of all available variable names in the telemetry file."""
        return self.var_names
