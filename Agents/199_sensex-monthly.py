import sys
import time
import calendar
from datetime import date
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client
import os

# =====================================================================
# Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"
DRAFT_TABLE = "data_points_draft"
DATASET_ID = 199
MAX_NAV_ATTEMPTS = 3   # Number of full navigation retries (site load through table load)
# =====================================================================

# Supabase Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Chrome Options Setup
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.page_load_strategy = 'eager'

# Automation detection bypass
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

chrome_options.add_argument("--window-size=1366,900")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def create_driver():
    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    d.set_page_load_timeout(60)
    w = WebDriverWait(d, 45)
    return d, w


def get_previous_completed_month():
    """
    Returns (month_num, year) for the most recently fully-completed month
    relative to today - e.g. run in Sep 2026 -> (8, 2026); run in Jan 2027
    -> (12, 2026). The current, still-in-progress month is never selected.
    """
    today = date.today()
    prev_month = today.month - 1
    prev_year = today.year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
    return prev_month, prev_year


def parse_monthly_dates(period_label):
    """
    Handles the format: 'Mar 2026' -> (2026-03-01, 2026-03-31)
    """
    try:
        parts = period_label.strip().split()
        if len(parts) != 2:
            return None, None

        month_str, year_str = parts[0].title(), parts[1]
        month_modules = {v: k for k, v in enumerate(calendar.month_abbr)}
        month_num = month_modules.get(month_str[:3])

        if not month_num:
            return None, None

        year = int(year_str)
        start_date = f"{year}-{month_num:02d}-01"
        last_day = calendar.monthrange(year, month_num)[1]
        end_date = f"{year}-{month_num:02d}-{last_day:02d}"

        return start_date, end_date
    except Exception as e:
        print(f"Error parsing monthly date: {e}")
        return None, None


def period_exists(table_name, dataset_id, period_label):
    """
    Checks whether a period_label exists in a table - a direct match, plus a
    safe fallback that normalizes en-dash/hyphen differences, in case rows
    were entered with a different dash character.
    """
    response = supabase.table(table_name).select("period_label").eq("dataset_id", dataset_id).eq("period_label", period_label).execute()
    if len(response.data) > 0:
        return True

    all_records = supabase.table(table_name).select("period_label").eq("dataset_id", dataset_id).execute()
    normalized_target = period_label.replace("–", "-").strip()
    for rec in all_records.data:
        db_label = rec.get("period_label", "").replace("–", "-").strip()
        if db_label == normalized_target:
            return True
    return False


def navigate_to_table(driver, wait, target_month_num, target_year):
    """
    Full flow: open the page, select Index=SENSEX, Period=Monthly, and the
    target from-month/from-year, click Submit, and wait for the results
    table to load. Raises an Exception on failure (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://www.bseindia.com/indices/indexarchivedata")

    print("Waiting for the Index dropdown...")
    index_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ddlIndex")))
    Select(index_dropdown).select_by_value("SENSEX")
    time.sleep(1)
    driver.save_screenshot("step1_index_selected.png")

    print("Selecting 'Monthly' in the Period dropdown...")
    period_dropdown = wait.until(EC.presence_of_element_located((By.ID, "Periodtype")))
    Select(period_dropdown).select_by_value("M")
    time.sleep(1)
    driver.save_screenshot("step2_period_selected.png")

    print(f"Selecting from-month {target_month_num:02d} and from-year {target_year}...")
    month_dropdown = wait.until(EC.presence_of_element_located((By.ID, "MfromMnth")))
    Select(month_dropdown).select_by_value(f"{target_month_num:02d}")
    time.sleep(1)

    year_dropdown = wait.until(EC.presence_of_element_located((By.ID, "MfromYr")))
    Select(year_dropdown).select_by_value(str(target_year))
    time.sleep(1)
    driver.save_screenshot("step3_month_year_selected.png")

    print("Clicking the Submit button...")
    submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='button' and @value='Submit']")))
    try:
        submit_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", submit_btn)

    print("Waiting for the results table to load...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//table[.//th[contains(text(), 'Close')]]")))
    time.sleep(3)
    driver.save_screenshot("step4_table_loaded.png")
    print("SUCCESS: Table loaded.")


driver, wait = create_driver()

try:
    target_month_num, target_year = get_previous_completed_month()
    target_period_label = f"{calendar.month_abbr[target_month_num]} {target_year}"
    print(f"Target period (most recently completed month): {target_period_label}")

    # ---- Run the full navigation flow with retries ----
    navigation_success = False
    for attempt in range(1, MAX_NAV_ATTEMPTS + 1):
        try:
            print(f"\n--- Navigation attempt {attempt}/{MAX_NAV_ATTEMPTS} ---")
            navigate_to_table(driver, wait, target_month_num, target_year)
            navigation_success = True
            break
        except Exception as e:
            print(f"Error during navigation attempt {attempt}: {e}")
            try:
                driver.save_screenshot(f"step_fail_attempt{attempt}.png")
            except Exception:
                pass
            if attempt == MAX_NAV_ATTEMPTS:
                break
            try:
                driver.quit()
            except Exception:
                pass
            time.sleep(10)
            driver, wait = create_driver()

    if not navigation_success:
        print("CRITICAL: All navigation attempts failed.")
        sys.exit(1)

    print("Reading table headers...")
    header_cells = driver.find_elements(By.XPATH, "//table[.//th[contains(text(), 'Close')]]//thead//th")
    header_texts = [(c.get_attribute("textContent") or "").strip() for c in header_cells]
    print(f"Headers found: {header_texts}")

    if "Close" not in header_texts:
        raise Exception(f"'Close' column not found in headers: {header_texts}")
    close_index = header_texts.index("Close")

    print("Reading the data row...")
    data_row = driver.find_element(By.XPATH, "//table[.//th[contains(text(), 'Close')]]//tbody//tr[1]")
    row_cells = data_row.find_elements(By.XPATH, "./td")

    month_text = (row_cells[0].get_attribute("textContent") or "").strip()
    print(f"Row's month label on page: '{month_text}'")

    if close_index >= len(row_cells):
        raise Exception(f"Close column index {close_index} is out of range for row with {len(row_cells)} cells.")

    raw_val = (row_cells[close_index].get_attribute("textContent") or "").strip()
    if not raw_val:
        raise Exception("Close value cell is empty.")

    value = float(raw_val.replace(',', '').strip())
    period_label = target_period_label

    print(f"\nProcessing Monthly Row -> Month: {period_label}, Close: {value}")

    valid_rows_count = 0

    # Step 1: Check if this period_label already exists in CHECK_TABLE (data_points)
    if period_exists(CHECK_TABLE, DATASET_ID, period_label):
        print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}'.")
    # Step 2: Not found in CHECK_TABLE, now check DRAFT_TABLE (data_points_draft) too
    elif period_exists(DRAFT_TABLE, DATASET_ID, period_label):
        print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}'.")
    else:
        # Step 3: Not found in either table - genuinely new data, insert into DRAFT_TABLE
        print(f"'{period_label}' is absent from both tables. Inserting new record into '{DRAFT_TABLE}'...")
        period_start, period_end = parse_monthly_dates(period_label)

        data_to_insert = {
            "dataset_id": DATASET_ID,
            "period_type": "MONTH",
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_end,
            "value": value,
            "is_active": False,
            "created_by": "c7dcaab6-1312-4d08-8b39-d327827d885f"
        }

        insert_resp = supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
        valid_rows_count += 1
        print(f"SUCCESS: New data for {period_label} inserted into '{DRAFT_TABLE}'.")

    print(f"\nScraping complete! {valid_rows_count} new row(s) inserted.")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
