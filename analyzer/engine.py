import pandas as pd
import numpy as np

class SetupAnalyzer:
    def __init__(self, dataframe: pd.DataFrame, session_info: dict = None):
        self.df = dataframe
        self.session_info = session_info
        self.recommendations = []
        self.diagnostics = {}

    def run_analysis(self):
        self.recommendations.clear()
        self.diagnostics.clear()

        if self.df is None or self.df.empty:
            self.recommendations.append("No telemetry data loaded.")
            return self.recommendations

        self._analyze_braking()
        self._analyze_cornering()
        self._analyze_ride_height()
        
        if not self.recommendations:
            self.recommendations.append("Your setup looks well-balanced based on this limited telemetry run.")
            
        return self.recommendations

    def _analyze_braking(self):
        # Look for instances of high braking and potential front/rear lockups
        # Often brake locking leads to wheel speed being much lower than ground speed.
        if 'Brake' not in self.df.columns or 'Speed' not in self.df.columns:
            return

        # Simple heuristic: high brake pressure
        high_brake_zones = self.df[self.df['Brake'] > 0.8]
        if not high_brake_zones.empty:
            self.diagnostics['Hard Braking Zones'] = len(high_brake_zones)
            
            # Check for locking if wheel speed channels exist
            wheel_speeds = ['LFspeed', 'RFspeed', 'LRspeed', 'RRspeed']
            if all(col in self.df.columns for col in wheel_speeds):
                for index, row in high_brake_zones.iterrows():
                    car_speed = row['Speed']
                    if car_speed > 10: # m/s
                        front_speed = (row['LFspeed'] + row['RFspeed']) / 2.0
                        rear_speed = (row['LRspeed'] + row['RRspeed']) / 2.0
                        
                        if front_speed < car_speed * 0.7:
                            self.recommendations.append(
                                "Front brakes are locking heavily under hard braking. Move brake bias REARWARD."
                            )
                            break
                        elif rear_speed < car_speed * 0.7:
                            self.recommendations.append(
                                "Rear brakes are locking under hard braking, causing instability. Move brake bias FORWARD."
                            )
                            break

    def _analyze_cornering(self):
        # Look for understeer or oversteer using steering angle and yaw rate/lateral Gs
        if 'SteeringWheelAngle' not in self.df.columns or 'YawRate' not in self.df.columns:
            return
            
        # Very rough heuristic: high steering angle but low yaw rate -> understeer
        # High yaw rate compared to steering angle -> oversteer
        # Since units and ratios vary per car, we look for extreme outliers in the session.
        
        # Focus on mid-corner (low throttle, low brake, high lat g)
        if 'Throttle' in self.df.columns and 'Brake' in self.df.columns and 'LatAccel' in self.df.columns:
            cornering = self.df[(self.df['Throttle'] < 0.2) & (self.df['Brake'] < 0.1) & (self.df['LatAccel'].abs() > 5.0)]
            
            if not cornering.empty:
                # Just placeholder heuristics for demonstration
                avg_steer_mag = cornering['SteeringWheelAngle'].abs().mean()
                avg_yaw_mag = cornering['YawRate'].abs().mean()
                
                # If steering is very high on average but yaw is relatively low
                if avg_steer_mag > 1.5 and avg_yaw_mag < 0.3:
                    self.recommendations.append("Possible Mid-Corner Understeer detected. Consider softening front ARB or stiffening rear ARB.")
                elif avg_yaw_mag > 0.8 and avg_steer_mag < 0.5:
                    self.recommendations.append("Possible Mid-Corner Oversteer detected. Consider stiffening front ARB or softening rear ARB.")

    def _analyze_ride_height(self):
        # Look for bottoming out
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if all(col in self.df.columns for col in rh_channels):
            for col in rh_channels:
                # If ride height goes below a threshold (e.g., 0.015m or 15mm depending on car)
                # iRacing usually stores in meters. Let's assume < 0.005m is scraping.
                min_rh = self.df[col].min()
                if min_rh < 0.005:
                    corner = col[:2]
                    self.recommendations.append(f"Bottoming out detected on {corner} corner (min {min_rh:.3f}m). Increase ride height or stiffen spring/packer.")
                    break
