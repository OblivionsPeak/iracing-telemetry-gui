import os
import pandas as pd
import irsdk

class TelemetryParser:
    def __init__(self):
        self.ibt = irsdk.IBT()
        self.file_path = None
        self.session_info = None
        self.dataframe = None

    def load_file(self, file_path: str):
        """Loads an .ibt file and parses it into a pandas DataFrame."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        self.file_path = file_path
        self.ibt.open(self.file_path)
        
        # Access session info (yaml dict)
        try:
            # Depending on pyirsdk version
            if hasattr(self.ibt, 'session_info_dict'):
                self.session_info = self.ibt.session_info_dict
            elif hasattr(self.ibt, '_IBT__session_info_dict'):
                self.session_info = self.ibt._IBT__session_info_dict
            else:
                self.session_info = {}
        except Exception:
            self.session_info = {}

        # Extract telemetry data
        # get_all() usually returns a generator or a list of dicts.
        try:
            samples = self.ibt.get_all()
            if not isinstance(samples, list):
                samples = list(samples)
            
            if samples:
                self.dataframe = pd.DataFrame(samples)
            else:
                self.dataframe = pd.DataFrame()
        except Exception as e:
            print(f"Error parsing samples: {e}")
            self.dataframe = pd.DataFrame()
            
        self.ibt.close()
        return self.dataframe, self.session_info

    def get_channels(self):
        if self.dataframe is not None:
            return self.dataframe.columns.tolist()
        return []
