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
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client
import os

# =====================================================================
# Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"
DRAFT_TABLE = "data_points_draft"
DATASET_ID = 156
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


def get_current_fiscal_year_start():
    """
    Fallback only: India's fiscal year runs April-March. Returns the
    starting calendar year of the fiscal year currently in progress.
    """
    today = date.today()
    return today.year if today.month >= 4 else today.year - 1


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


def navigate_to_table(driver, wait):
    """
    Opens the page and waits for the price table to be present.
    This site is a plain server-rendered page - no search box, dropdown,
    or iframe navigation is needed, unlike the RBI DBIE reports.
    Raises an Exception on failure (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://ppac.gov.in/prices/international-prices-of-diesel")

    print("Waiting for the price table to load...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//table[.//th[contains(text(), 'April')]]")))
    time.sleep(3)
    driver.save_screenshot("step1_table_loaded.png")
    print("SUCCESS: Table loaded.")


driver, wait = create_driver()

try:
    # ---- Run the full navigation flow with retries ----
    navigation_success = False
    for attempt in range(1, MAX_NAV_ATTEMPTS + 1):
        try:
            print(f"\n--- Navigation attempt {attempt}/{MAX_NAV_ATTEMPTS} ---")
            navigate_to_table(driver, wait)
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

    print("Reading table rows...")
    table_rows = driver.find_elements(By.XPATH, "//table[.//th[contains(text(), 'April')]]//tr")
    if len(table_rows) < 2:
        raise Exception(f"Expected a header row and a price row, but found {len(table_rows)} row(s).")

    header_row = table_rows[0]
    price_row = table_rows[1]

    print("Reading month headers...")
    header_cells = header_row.find_elements(By.XPATH, "./th")
    month_headers = []
    for cell in header_cells:
        text = (cell.get_attribute("textContent") or "").strip()
        if text and text not in ("Year", "Total", "Historical Data"):
            month_headers.append(text)
    print(f"Month columns found: {month_headers}")

    print("Reading fiscal year from the price row...")
    year_cell = price_row.find_element(By.XPATH, "./td[1]")
    year_text = (year_cell.get_attribute("textContent") or "").strip()
    fiscal_year_start = None
    try:
        fiscal_year_start = int(year_text.split('-')[0].strip())
    except Exception as e:
        print(f"Could not parse fiscal year from '{year_text}': {e}")

    if not fiscal_year_start:
        fiscal_year_start = get_current_fiscal_year_start()
        print(f"Using date-based fiscal year fallback: {fiscal_year_start}-{fiscal_year_start + 1}")
    else:
        print(f"Fiscal year read from table: {year_text}")

    value_cells = price_row.find_elements(By.XPATH, "./td[position() > 1]")

    scraped_data_list = []
    for i, month_name in enumerate(month_headers):
        try:
            if i >= len(value_cells):
                continue
            raw_val = (value_cells[i].get_attribute("textContent") or "").strip()
            if not raw_val:
                continue

            month_num = None
            try:
                month_num = list(calendar.month_name).index(month_name.title())
            except ValueError:
                pass
            if not month_num:
                print(f"Skip: could not recognize month name '{month_name}'.")
                continue

            year = fiscal_year_start if month_num >= 4 else fiscal_year_start + 1

            # Skip the current, still-in-progress month - the site updates
            # this month's price daily as crude oil prices fluctuate, so
            # only fully completed months should be scraped.
            today = date.today()
            if (year, month_num) >= (today.year, today.month):
                print(f"Skip: '{calendar.month_abbr[month_num]} {year}' has not fully completed yet.")
                continue

            period_label = f"{calendar.month_abbr[month_num]} {year}"
            value = float(raw_val.replace(',', '').strip())
            scraped_data_list.append({"period_label": period_label, "value": value})
        except Exception as e:
            print(f"Skip (column '{month_name}'): {e}")
            continue

    print(f"Total months with data found: {len(scraped_data_list)}")

    valid_rows_count = 0
    failed_rows = []
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]

            print(f"\nProcessing Monthly Column -> Month: {period_label}, Value: {value}")

            # Step 1: Check if this period_label already exists in CHECK_TABLE (data_points)
            if period_exists(CHECK_TABLE, DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}'.")
                continue

            # Step 2: Not found in CHECK_TABLE, now check DRAFT_TABLE (data_points_draft) too
            if period_exists(DRAFT_TABLE, DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}'.")
                continue

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

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            failed_rows.append({"period_label": item.get("period_label", "unknown"), "error": str(row_err)})
            continue

    print(f"\nScraping complete! Total {len(scraped_data_list)} monthly columns found, {valid_rows_count} new row(s) inserted.")

    if len(scraped_data_list) == 0:
        print("CRITICAL: Not a single month column had data - the site structure may have changed or selectors failed.")
        sys.exit(1)

    if failed_rows:
        print(f"\nWARNING: {len(failed_rows)} row(s) failed while processing:")
        for f in failed_rows:
            print(f"  - {f['period_label']}: {f['error']}")
        sys.exit(1)

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
