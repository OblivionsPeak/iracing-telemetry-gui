# iRacing Telemetry Setup Analyzer

A Python desktop application that analyzes iRacing telemetry data (`.ibt` files) specifically for road courses. It processes telemetry metrics and provides actionable feedback on car setup adjustments to help drivers improve their lap times.

## Features
- **Parse `.ibt` files:** Leverages `pyirsdk` to read telemetry data.
- **Telemetry Charts:** Visualizes Speed, Throttle, and Brake inputs.
- **Setup Recommendations:** Automatically analyzes the telemetry to detect issues like:
  - Brake locking (Front/Rear)
  - Understeer/Oversteer tendencies mid-corner
  - Suspension bottoming out

## Requirements
- Python 3.10+
- See `requirements.txt` for Python packages (`pandas`, `numpy`, `PyQt6`, `pyqtgraph`, `pyirsdk`).

## Installation
1. Clone the repository:
   ```bash
   git clone <repository_url>
   cd iracing-telemetry-gui
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
Run the main script to launch the GUI:
```bash
python main.py
```
Click "Load .ibt File" and select an iRacing telemetry file. The app will generate charts and suggest setup tweaks in the left panel.
