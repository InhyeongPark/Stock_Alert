"""
DST Check and Workflow Auto-Update
Runs every Monday at 6:00 AM (NewYork Timezone)
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

def check_and_update_dst():
    """Update workflow after checking for DST status (US Eastern Time)."""
    
    # Current US Easter Time
    et_now = datetime.now(ZoneInfo("America/New_York"))
    
    # Check if it is DST (tm_isdst)
    is_dst = bool(et_now.dst())
    
    # If DST, UTC = 13:00 else 14:00
    cron_hour = "13" if is_dst else "14"
    new_cron = f'"0 {cron_hour} * * 1-5"'
    
    workflow_path = ".github/workflows/daily_stock_report.yml"
    
    with open(workflow_path, "r") as f:
        content = f.read()
    
    # Cron Line Update
    import re
    updated_content = re.sub(
        r'cron: "0 1[34] \* \* 1-5"',
        f'cron: {new_cron}',
        content
    )
    
    if content != updated_content:
        with open(workflow_path, "w") as f:
            f.write(updated_content)
        print(f"Updated cron to {new_cron} (DST: {is_dst})")
        return True
    else:
        print(f"No change needed (DST: {is_dst})")
        return False

if __name__ == "__main__":
    check_and_update_dst()
