import requests
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from pathlib import Path
import sys

class KalshiTemperaturePredictor:
    """
    Temperature prediction system optimized for Kalshi day trading
    Shows only TODAY'S prediction for multiple locations
    Uses Climatological Report (CLI) standards
    """
    
    def __init__(self, location='Miami', lat=25.7617, lon=-80.1918):
        """Initialize calculator with location"""
        self.location = location
        self.lat = lat
        self.lon = lon
        
        # Set output directory
        self.output_dir = Path.home() / 'Desktop' / 'Daily-Temperature-Prediction'
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_open_meteo_ecmwf(self):
        """Fetch ECMWF IFS forecast (most accurate global model)"""
        try:
            url = "https://api.open-meteo.com/v1/ecmwf"
            params = {
                'latitude': self.lat,
                'longitude': self.lon,
                'daily': 'temperature_2m_max,temperature_2m_min',
                'temperature_unit': 'fahrenheit',
                'timezone': 'America/New_York',
                'forecast_days': 1  # Only today
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'daily' in data and 'time' in data['daily']:
                date = datetime.fromisoformat(data['daily']['time'][0]).date()
                return {
                    'date': date,
                    'high': data['daily']['temperature_2m_max'][0],
                    'low': data['daily']['temperature_2m_min'][0],
                    'source': 'ECMWF_IFS'
                }
            return None
            
        except Exception as e:
            print(f"  ✗ ECMWF failed: {e}")
            return None
    
    def fetch_open_meteo_multi_model(self):
        """Fetch multi-model ensemble forecast"""
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                'latitude': self.lat,
                'longitude': self.lon,
                'daily': 'temperature_2m_max,temperature_2m_min',
                'temperature_unit': 'fahrenheit',
                'timezone': 'America/New_York',
                'forecast_days': 1  # Only today
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'daily' in data and 'time' in data['daily']:
                date = datetime.fromisoformat(data['daily']['time'][0]).date()
                return {
                    'date': date,
                    'high': data['daily']['temperature_2m_max'][0],
                    'low': data['daily']['temperature_2m_min'][0],
                    'source': 'Multi_Model'
                }
            return None
            
        except Exception as e:
            print(f"  ✗ Multi-model failed: {e}")
            return None
    
    def get_today_prediction(self):
        """Get today's prediction with ensemble weighting"""
        ecmwf = self.fetch_open_meteo_ecmwf()
        multi = self.fetch_open_meteo_multi_model()
        
        if not ecmwf and not multi:
            return None
        
        # Weighted ensemble: ECMWF 60%, Multi 40%
        highs = []
        lows = []
        
        if ecmwf:
            highs.extend([ecmwf['high']] * 3)
            lows.extend([ecmwf['low']] * 3)
        
        if multi:
            highs.extend([multi['high']] * 2)
            lows.extend([multi['low']] * 2)
        
        # Calculate consensus - round to match CLI reporting
        return {
            'location': self.location,
            'date': ecmwf['date'] if ecmwf else multi['date'],
            'high': round(np.mean(highs)),
            'low': round(np.mean(lows)),
            'high_std': np.std(highs),
            'low_std': np.std(lows)
        }
    
    def predict_multiple_locations(self, locations):
        """
        Predict TODAY'S temperatures for multiple locations
        
        locations: list of dicts with keys 'name', 'lat', 'lon'
        """
        predictions = []
        
        print(f"\n{'='*70}")
        print(f"FETCHING TODAY'S PREDICTIONS FOR {len(locations)} LOCATIONS")
        print(f"{'='*70}\n")
        
        for loc in locations:
            print(f"Processing: {loc['name']}...", end=" ")
            
            # Update location
            self.location = loc['name']
            self.lat = loc['lat']
            self.lon = loc['lon']
            
            # Get prediction
            pred = self.get_today_prediction()
            
            if pred:
                predictions.append(pred)
                print("✓")
            else:
                print("✗ Failed")
        
        if predictions:
            # Convert to DataFrame
            df = pd.DataFrame(predictions)
            
            # Display results
            print(f"\n{'='*70}")
            print("TODAY'S TEMPERATURE PREDICTIONS")
            print(f"Date: {predictions[0]['date']}")
            print(f"{'='*70}\n")
            
            for pred in predictions:
                print(f"{pred['location']:20} | High: {pred['high']:3.0f}°F (±{pred['high_std']:.1f}) | Low: {pred['low']:3.0f}°F (±{pred['low_std']:.1f})")
            
            # Save to CSV
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = self.output_dir / f"today_predictions_{timestamp}.csv"
            df.to_csv(output_file, index=False)
            
            print(f"\n{'='*70}")
            print(f"✓ Predictions saved to: {output_file}")
            print(f"{'='*70}\n")
            
            return df
        
        return pd.DataFrame()


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("KALSHI DAY TRADING - TODAY'S TEMPERATURE PREDICTIONS")
    print("="*70)
    
    # Default major markets for Kalshi
    DEFAULT_LOCATIONS = [
        {'name': 'New York', 'lat': 40.7829, 'lon': -73.9654},      # Central Park
        {'name': 'Los Angeles', 'lat': 33.9416, 'lon': -118.4085},  # LAX Airport
        {'name': 'Chicago', 'lat': 41.7868, 'lon': -87.7522},       # Midway Airport
        {'name': 'Philadelphia', 'lat': 39.8729, 'lon': -75.2437},  # Philadelphia Airport (PHL)
        {'name': 'Austin', 'lat': 30.1945, 'lon': -97.6699},        # Austin-Bergstrom Airport
        {'name': 'Denver', 'lat': 39.8561, 'lon': -104.6737},       # Denver Airport
        {'name': 'Miami', 'lat': 25.7959, 'lon': -80.2870},         # Miami International Airport
    ]
    
    locations = []
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            parts = arg.split(',')
            if len(parts) == 3:
                try:
                    locations.append({
                        'name': parts[0].strip(),
                        'lat': float(parts[1].strip()),
                        'lon': float(parts[2].strip())
                    })
                except ValueError:
                    print(f"Warning: Invalid format for '{arg}'. Skipping.")
            else:
                print(f"Warning: Invalid format for '{arg}'. Use: 'Name,lat,lon'")
    
    # If no valid locations from command line, use defaults
    if not locations:
        print("\nNo locations specified. Using default 25 major US cities.")
        print("Usage: python Daily_Temp.py 'Miami,25.7617,-80.1918' 'NYC,40.7128,-74.0060' ...")
        locations = DEFAULT_LOCATIONS
    
    # Run predictions
    predictor = KalshiTemperaturePredictor()
    predictions = predictor.predict_multiple_locations(locations)
    
    if not predictions.empty:
        print("\nQuick Stats:")
        print(f"  Average High: {predictions['high'].mean():.0f}°F")
        print(f"  Average Low: {predictions['low'].mean():.0f}°F")
        print(f"  Most confident prediction: {predictions.loc[predictions['high_std'].idxmin(), 'location']} (±{predictions['high_std'].min():.1f}°F)")
    else:
        print("\n✗ No predictions generated. Check your internet connection.")