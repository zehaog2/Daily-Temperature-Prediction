import requests
import re
from datetime import datetime, timedelta

# City names mapping
CITY_NAMES = {
    'KLAS': 'Las Vegas', 'KPHL': 'Philadelphia', 'KLAX': 'Los Angeles',
    'KMIA': 'Miami', 'KDEN': 'Denver', 'KDCA': 'Washington DC',
    'KAUS': 'Austin', 'KSEA': 'Seattle', 'KMSY': 'New Orleans',
    'KORD': 'Chicago', 'KATL': 'Atlanta', 'KDFW': 'Dallas',
    'KPHX': 'Phoenix', 'KPDX': 'Portland', 'KBOS': 'Boston',
    'KJFK': 'New York JFK', 'KLGA': 'New York LGA', 'KMDW': 'Chicago Midway',
    'KSFO': 'San Francisco', 'KNYC': 'New York Central Park'
}

# Timezone offsets from UTC
STATION_TIMEZONES = {
    'KPHL': -5, 'KDCA': -5, 'KMIA': -5, 'KATL': -5, 'KBOS': -5, 
    'KJFK': -5, 'KLGA': -5, 'KNYC': -5,  # EST
    'KAUS': -6, 'KMSY': -6, 'KORD': -6, 'KDFW': -6, 'KMDW': -6,  # CST
    'KDEN': -7, 'KPHX': -7,  # MST
    'KLAX': -8, 'KSEA': -8, 'KPDX': -8, 'KSFO': -8, 'KLAS': -8,  # PST
}

TZ_NAMES = {-5: 'EST', -6: 'CST', -7: 'MST', -8: 'PST'}

def parse_metar_time(raw_metar):
    """
    Parse timestamp directly from METAR text.
    Format: DDHHMM (day, hour, minute in UTC)
    Example: 190351Z means Jan 19, 03:51 UTC
    """
    match = re.search(r'\b(\d{2})(\d{2})(\d{2})Z\b', raw_metar)
    if not match:
        return None
    
    day = int(match.group(1))
    hour = int(match.group(2))
    minute = int(match.group(3))
    
    # Get current UTC time to determine year and month
    now = datetime.utcnow()
    
    # Try current month first
    try:
        dt = datetime(now.year, now.month, day, hour, minute, 0)
        # If the date is more than 15 days in the future, it's probably last month
        if (dt - now).days > 15:
            if now.month == 1:
                dt = datetime(now.year - 1, 12, day, hour, minute, 0)
            else:
                dt = datetime(now.year, now.month - 1, day, hour, minute, 0)
        return dt.isoformat() + 'Z'
    except ValueError:
        # Day doesn't exist in current month, try previous month
        if now.month == 1:
            dt = datetime(now.year - 1, 12, day, hour, minute, 0)
        else:
            dt = datetime(now.year, now.month - 1, day, hour, minute, 0)
        return dt.isoformat() + 'Z'

def utc_to_et(utc_time_str):
    """Convert UTC time string to Eastern Time."""
    utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    et_time = utc_time + timedelta(hours=-5)
    return et_time.strftime('%I:%M%p ET').lstrip('0').lower()

def utc_to_local(utc_time_str, tz_offset):
    """Convert UTC time to local timezone."""
    utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    local_time = utc_time + timedelta(hours=tz_offset)
    return local_time

def format_local_time(utc_time_str, tz_offset, tz_name):
    """Format time in local timezone."""
    local_time = utc_to_local(utc_time_str, tz_offset)
    return local_time.strftime(f'%I:%M%p {tz_name}').lstrip('0').lower()

def scan(station_id, debug=False, trade_date=None):
    """
    Comprehensive METAR analysis for single city trading.
    Returns detailed report with all observations for the trading day.
    
    Args:
        station_id: Airport code (e.g., 'KNYC')
        debug: Print debug information
        trade_date: Specific date to analyze (datetime.date object). 
                   If None, uses current EST date.
    """
    station_id = station_id.upper()
    
    try:
        # Get timezone for this station
        tz_offset = STATION_TIMEZONES.get(station_id, -5)
        tz_name = TZ_NAMES.get(tz_offset, 'UTC')
        
        # Determine target date - always use EST date when code is run
        if trade_date is None:
            # Get current EST time
            est_now = datetime.utcnow() + timedelta(hours=-5)
            target_date = est_now.date()
        else:
            target_date = trade_date
        
        if debug:
            print(f"Target trading date (EST): {target_date}")
        
        # Fetch 48 hours to ensure completeness
        r = requests.get(
            "https://aviationweather.gov/api/data/metar",
            params={'ids': station_id, 'format': 'json', 'hours': 48},
            timeout=5
        )
        
        if debug:
            print(f"API Status: {r.status_code}")
            print(f"Response length: {len(r.text)}")
        
        data = r.json()
        
        if debug:
            print(f"Total observations received: {len(data)}")
            if data:
                print(f"First observation sample: {data[0].get('rawOb', 'N/A')[:100]}")
        
        # Decode all T-fields
        obs = []
        for o in data:
            raw_ob = o.get('rawOb', '')
            m = re.search(r'T([01])(\d{3})', raw_ob)
            if m:
                c = int(m.group(2)) / 10.0
                if m.group(1) == '1': c = -c
                f = c * 9/5 + 32
                true = round(f)
                displayed = round(round(c) * 9/5 + 32, 1)
                
                # Try to parse time from raw METAR first, fallback to API reportTime
                parsed_time = parse_metar_time(raw_ob)
                utc_time = parsed_time if parsed_time else o['reportTime']
                
                obs.append({
                    'true': true,
                    'displayed': displayed,
                    'temp_c': c,
                    'utc_time': utc_time,
                    'raw_text': raw_ob
                })
        
        if debug:
            print(f"Observations with T-field: {len(obs)}")
        
        if not obs:
            return {'ERROR': f'No T-field data found in {len(data)} observations', 'station': station_id}
        
        # Filter to target EST date (current date data only)
        # Convert all observations to EST for filtering
        today_obs = [o for o in obs 
                     if utc_to_local(o['utc_time'], -5).date() == target_date]
        
        if debug:
            print(f"Observations for {target_date} (EST): {len(today_obs)}")
            if today_obs:
                first_time = utc_to_local(today_obs[0]['utc_time'], -5)
                last_time = utc_to_local(today_obs[-1]['utc_time'], -5)
                print(f"Time range: {first_time} to {last_time}")
        
        # If no data for current date, fall back to last 12 hours from previous day
        if not today_obs:
            if debug:
                print(f"No data for {target_date}, falling back to last 12 hours")
            
            # Get current EST time (timezone-naive for comparison)
            est_now = datetime.utcnow() + timedelta(hours=-5)
            twelve_hours_ago = est_now - timedelta(hours=12)
            
            # Filter to last 12 hours (convert to naive datetime for comparison)
            today_obs = []
            for o in obs:
                obs_time = utc_to_local(o['utc_time'], -5)
                # Make sure both are naive for comparison
                if isinstance(obs_time, datetime):
                    obs_time = obs_time.replace(tzinfo=None)
                if obs_time >= twelve_hours_ago:
                    today_obs.append(o)
            
            if debug:
                print(f"Observations in last 12 hours: {len(today_obs)}")
                if today_obs:
                    first_time = utc_to_local(today_obs[0]['utc_time'], -5)
                    last_time = utc_to_local(today_obs[-1]['utc_time'], -5)
                    print(f"Time range: {first_time} to {last_time}")
            
            if not today_obs:
                return {'ERROR': f'No observations for {target_date} (EST) or last 12 hours', 'station': station_id}
        
        # Find max and min
        max_obs = max(today_obs, key=lambda x: x['true'])
        min_obs = min(today_obs, key=lambda x: x['true'])
        last_obs = max(today_obs, key=lambda x: x['utc_time'])
        
        return {
            'station': station_id,
            'city': CITY_NAMES.get(station_id, station_id),
            'date': target_date,
            'timezone': 'EST',  # Always show EST since we're filtering by EST
            'tz_offset': -5,     # Always use EST offset for display
            
            'max_obs': max_obs,
            'min_obs': min_obs,
            'last_obs': last_obs,
            'all_obs': today_obs,
            
            'MAX_TRUE': max_obs['true'],
            'MAX_MARKET': max_obs['displayed'],
            'MAX_EDGE': max_obs['true'] - max_obs['displayed'],
            'MAX_TIME_ET': utc_to_et(max_obs['utc_time']),
            'MAX_TIME_LOCAL': format_local_time(max_obs['utc_time'], -5, 'EST'),
            'MAX_OPPORTUNITY': abs(max_obs['true'] - max_obs['displayed']) >= 0.5,
            
            'MIN_TRUE': min_obs['true'],
            'MIN_MARKET': min_obs['displayed'],
            'MIN_EDGE': min_obs['true'] - min_obs['displayed'],
            'MIN_TIME_ET': utc_to_et(min_obs['utc_time']),
            'MIN_TIME_LOCAL': format_local_time(min_obs['utc_time'], -5, 'EST'),
            'MIN_OPPORTUNITY': abs(min_obs['true'] - min_obs['displayed']) >= 0.5,
            
            'LAST_OBS_ET': utc_to_et(last_obs['utc_time']),
            'LAST_OBS_LOCAL': format_local_time(last_obs['utc_time'], -5, 'EST'),
            'TOTAL_OBS': len(today_obs),
        }
        
    except Exception as e:
        return {'ERROR': str(e), 'station': station_id}


def report(station_id, trade_type='MAX'):
    """
    Comprehensive daily report for single city trading.
    
    Args:
        station_id: Airport code (e.g., 'KLAS', 'KPHL')
        trade_type: 'MAX' or 'MIN'
    """
    result = scan(station_id)
    
    if not result or 'ERROR' in result:
        print(f"\n{station_id}: NO DATA AVAILABLE")
        return None
    
    # Header
    print(f"\n{'='*80}")
    print(f"TRADING REPORT: {result['station']} ({result['city']})")
    print(f"Date: {result['date']} {result['timezone']}")
    print(f"{'='*80}\n")
    
    # Last observation
    print(f"Last Observation: {result['LAST_OBS_LOCAL']} ({result['LAST_OBS_ET']})")
    print(f"Total Observations Today: {result['TOTAL_OBS']}")
    print()
    
    # Focus on requested trade type
    if trade_type == 'MAX':
        print(f"MAXIMUM TEMPERATURE ANALYSIS:")
        print(f"{'-'*80}")
        print(f"TRUE Maximum: {result['MAX_TRUE']}F")
        print(f"Market Sees: {result['MAX_MARKET']}F")
        print(f"Your Edge: {result['MAX_EDGE']:+.1f}F")
        print(f"Occurred At: {result['MAX_TIME_LOCAL']} ({result['MAX_TIME_ET']})")
        print()
        
        if result['MAX_OPPORTUNITY']:
            print(f"TRADE SIGNAL: YES (Edge >= 0.5F)")
            print(f"Action: Bet on MAX = {result['MAX_TRUE']}F")
        else:
            print(f"TRADE SIGNAL: NO (Edge < 0.5F)")
        print()
        
        # Show nearby observations
        print(f"Observations Around Maximum:")
        print(f"{'-'*80}")
        print(f"{'Time (Local)':<20} {'Time (ET)':<15} {'TRUE':<8} {'Market':<8} {'Edge':<8}")
        print(f"{'-'*80}")
        
        # Sort by time
        sorted_obs = sorted(result['all_obs'], key=lambda x: x['utc_time'])
        max_idx = next(i for i, o in enumerate(sorted_obs) if o['utc_time'] == result['max_obs']['utc_time'])
        
        # Show 3 before and 3 after
        start = max(0, max_idx - 3)
        end = min(len(sorted_obs), max_idx + 4)
        
        for obs in sorted_obs[start:end]:
            local_time = format_local_time(obs['utc_time'], result['tz_offset'], result['timezone'])
            et_time = utc_to_et(obs['utc_time'])
            marker = " <-- MAX" if obs['utc_time'] == result['max_obs']['utc_time'] else ""
            print(f"{local_time:<20} {et_time:<15} {obs['true']:<8}F {obs['displayed']:<8}F {obs['true']-obs['displayed']:+.1f}F{marker}")
    
    else:  # MIN
        print(f"MINIMUM TEMPERATURE ANALYSIS:")
        print(f"{'-'*80}")
        print(f"TRUE Minimum: {result['MIN_TRUE']}F")
        print(f"Market Sees: {result['MIN_MARKET']}F")
        print(f"Your Edge: {result['MIN_EDGE']:+.1f}F")
        print(f"Occurred At: {result['MIN_TIME_LOCAL']} ({result['MIN_TIME_ET']})")
        print()
        
        if result['MIN_OPPORTUNITY']:
            print(f"TRADE SIGNAL: YES (Edge >= 0.5F)")
            print(f"Action: Bet on MIN = {result['MIN_TRUE']}F")
        else:
            print(f"TRADE SIGNAL: NO (Edge < 0.5F)")
        print()
        
        # Show nearby observations
        print(f"Observations Around Minimum:")
        print(f"{'-'*80}")
        print(f"{'Time (Local)':<20} {'Time (ET)':<15} {'TRUE':<8} {'Market':<8} {'Edge':<8}")
        print(f"{'-'*80}")
        
        sorted_obs = sorted(result['all_obs'], key=lambda x: x['utc_time'])
        min_idx = next(i for i, o in enumerate(sorted_obs) if o['utc_time'] == result['min_obs']['utc_time'])
        
        start = max(0, min_idx - 3)
        end = min(len(sorted_obs), min_idx + 4)
        
        for obs in sorted_obs[start:end]:
            local_time = format_local_time(obs['utc_time'], result['tz_offset'], result['timezone'])
            et_time = utc_to_et(obs['utc_time'])
            marker = " <-- MIN" if obs['utc_time'] == result['min_obs']['utc_time'] else ""
            print(f"{local_time:<20} {et_time:<15} {obs['true']:<8}F {obs['displayed']:<8}F {obs['true']-obs['displayed']:+.1f}F{marker}")
    
    print(f"\n{'='*80}")
    print(f"NOTE: Analysis based on hourly METAR observations with T-field.")
    print(f"      Actual extremes may occur between hourly observations.")
    print(f"{'='*80}\n")
    
    return result


# ============================================================================
# USAGE
# ============================================================================

if __name__ == "__main__":
    report('KMIA', 'MAX')