import sys
import time
import calendar
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
MAX_NAV_ATTEMPTS = 3   # Number of full navigation retries (site load through table load)
DATASETS = 
    [
    {"dataset_id": 63, "column_index": 2, "label": "P2P Volume"},
    {"dataset_id": 64, "column_index": 4, "label": "P2M Volume"},
    {"dataset_id": 65, "column_index": 3, "label": "P2P Value"},
    {"dataset_id": 66, "column_index": 5, "label": "P2M Value"},
    ]
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
    Opens the page, switches to the 'P2P and P2M Transactions' tab, and
    waits for the results table to load. Raises an Exception on failure
    at any step (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://www.npci.org.in/product/ecosystem-statistics/upi")

    print("Waiting for the page to settle...")
    time.sleep(5)
    driver.save_screenshot("step1_initial_page.png")

    print("Clicking the 'P2P and P2M Transactions' tab...")
    tab = None
    try:
        tab = wait.until(EC.element_to_be_clickable((By.ID, "tab-3")))
    except Exception:
        tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@role='tab' and contains(text(), 'P2P and P2M Transactions')]")))

    try:
        tab.click()
    except Exception:
        driver.execute_script("arguments[0].click();", tab)
    time.sleep(3)
    driver.save_screenshot("step2_tab_selected.png")

    print("Waiting for the results table to load...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(@class, 'custom-table')][.//span[contains(text(), 'P2P')]]")))
    time.sleep(2)
    driver.save_screenshot("step3_table_loaded.png")
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

    print("Reading the data row...")
    table = driver.find_element(By.XPATH, "//table[contains(@class, 'custom-table')][.//span[contains(text(), 'P2P')]]")
    data_row = table.find_element(By.XPATH, ".//tbody/tr[1]")

    month_cell = data_row.find_element(By.XPATH, "./td[1]")
    month_text = (month_cell.get_attribute("textContent") or "").strip()
    print(f"Month label on page: '{month_text}'")

    # Format on the site is 'Aug-26' -> convert to 'Aug 2026'
    mon_part, _, yr_part = month_text.partition('-')
    if not mon_part or not yr_part:
        raise Exception(f"Could not parse month label '{month_text}'.")
    full_year = f"20{yr_part.strip()}" if len(yr_part.strip()) == 2 else yr_part.strip()
    period_label = f"{mon_part.strip().title()} {full_year}"
    print(f"Resolved period label: {period_label}")

    value_cells = data_row.find_elements(By.XPATH, "./td[position() > 1]")
    print(f"Total value columns found: {len(value_cells)}")

    valid_rows_count = 0
    failed_datasets = []

    for cfg in DATASETS:
        try:
            dataset_id = cfg["dataset_id"]
            column_index = cfg["column_index"]
            label = cfg["label"]

            if column_index >= len(value_cells):
                raise Exception(f"Column index {column_index} out of range for {len(value_cells)} value cells.")

            raw_val = (value_cells[column_index].get_attribute("textContent") or "").strip()
            if not raw_val:
                raise Exception("Value cell is empty.")

            value = float(raw_val.replace(',', '').strip())
            print(f"\nProcessing dataset {dataset_id} ({label}) -> Month: {period_label}, Value: {value}")

            # Step 1: Check if this period_label already exists in CHECK_TABLE (data_points)
            if period_exists(CHECK_TABLE, dataset_id, period_label):
                print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}' for dataset {dataset_id}.")
                continue

            # Step 2: Not found in CHECK_TABLE, now check DRAFT_TABLE (data_points_draft) too
            if period_exists(DRAFT_TABLE, dataset_id, period_label):
                print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}' for dataset {dataset_id}.")
                continue

            # Step 3: Not found in either table - genuinely new data, insert into DRAFT_TABLE
            print(f"'{period_label}' is absent from both tables for dataset {dataset_id}. Inserting new record into '{DRAFT_TABLE}'...")
            period_start, period_end = parse_monthly_dates(period_label)

            data_to_insert = {
                "dataset_id": dataset_id,
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
            print(f"SUCCESS: New data for dataset {dataset_id} ({period_label}) inserted into '{DRAFT_TABLE}'.")

        except Exception as ds_err:
            print(f"Dataset {cfg.get('dataset_id', 'unknown')} error: {ds_err}")
            failed_datasets.append({"dataset_id": cfg.get("dataset_id", "unknown"), "error": str(ds_err)})
            continue

    print(f"\nScraping complete! {valid_rows_count} new row(s) inserted across {len(DATASETS)} datasets.")

    if failed_datasets:
        print(f"\nWARNING: {len(failed_datasets)} dataset(s) failed while processing:")
        for f in failed_datasets:
            print(f"  - dataset {f['dataset_id']}: {f['error']}")
        sys.exit(1)

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
