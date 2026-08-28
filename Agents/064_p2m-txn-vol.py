import time
import sys
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
# CONFIGURATION: Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"
DRAFT_TABLE = "data_points_draft"
DATASET_ID = 64
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

chrome_options.add_argument("--window-size=1366,768")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def create_driver():
    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    d.set_page_load_timeout(90)
    w = WebDriverWait(d, 60)
    return d, w


def normalize_month_year(raw_text):
    """
    Handles the site's format: 'July-26' -> 'Jul 2026'
    (Full month name + hyphen + 2-DIGIT year) -> (Abbreviated month +
    space + 4-digit year), to match the convention used across all other
    monthly datasets in Supabase. Also tolerant of a 4-digit year input,
    in case the site's format changes later.
    """
    try:
        raw_text = raw_text.strip()
        if '-' not in raw_text:
            return None

        month_part, year_part = raw_text.split('-', 1)
        month_part = month_part.strip().title()
        year_part = year_part.strip()

        full_to_abbr = {calendar.month_name[i]: calendar.month_abbr[i] for i in range(1, 13)}
        month_abbr = full_to_abbr.get(month_part)

        if not month_abbr:
            # Defensive fallback in case it's already abbreviated
            valid_abbrs = [a for a in calendar.month_abbr if a]
            if month_part in valid_abbrs:
                month_abbr = month_part
            else:
                month_abbr = month_part[:3]

        # This site uses a 2-digit year (e.g. '26') - expand to 4 digits.
        if year_part.isdigit() and len(year_part) == 2:
            year_part = "20" + year_part

        return f"{month_abbr} {year_part}"
    except Exception as e:
        print(f"Error normalizing month/year '{raw_text}': {e}")
        return None


def parse_monthly_dates(period_label):
    """
    Handles the format: 'Jul 2026' -> (2026-07-01, 2026-07-31)
    """
    try:
        parts = period_label.strip().split()
        if len(parts) != 2:
            return None, None

        month_str, year_str = parts[0].title(), parts[1]
        month_modules = {v: k for k, v in enumerate(calendar.month_abbr)}
        month_num = month_modules.get(month_str[:3])

        if not month_num:
            month_modules_full = {v: k for k, v in enumerate(calendar.month_name)}
            month_num = month_modules_full.get(month_str)

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


def parse_value(raw_val):
    """
    The site reports the P2M Transaction Volume in Millions (with 2
    decimal places, e.g. '14,971.85'), and Supabase stores it in the same
    unit - no conversion needed, just strip the comma grouping and parse
    the number.
    e.g. '14,971.85' -> 14971.85
    """
    cleaned = raw_val.replace(',', '').strip()
    return int(cleaned) if '.' not in cleaned else float(cleaned)


def navigate_to_table(driver, wait):
    """
    Full flow from opening the site to the data table being loaded.
    This is the 'Ecosystem Statistics' page, whose default tab is
    'Chargeback' - an extra tab-click to 'P2P and P2M Transactions' is
    needed before the correct table (with the P2P/P2M columns) renders.
    Raises an Exception on failure at any step (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://www.npci.org.in/product/ecosystem-statistics/upi")

    print("Waiting explicitly for the page to settle...")
    time.sleep(10)
    driver.save_screenshot("step1_initial_page.png")

    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(2)
    except Exception:
        pass

    print("Waiting for the default 'Chargeback' tab's table to load first...")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.custom-table")))
    driver.save_screenshot("step2_default_tab_loaded.png")

    print("Clicking the 'P2P and P2M Transactions' tab...")
    p2m_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='tab' and contains(text(), 'P2P and P2M Transactions')]")))
    try:
        p2m_tab.click()
    except Exception:
        driver.execute_script("arguments[0].click();", p2m_tab)
    time.sleep(5)
    driver.save_screenshot("step3_p2m_tab_clicked.png")

    print("Waiting for the P2P/P2M table (with 'P2M' header) to load...")
    wait.until(lambda d: "P2M" in d.find_element(By.CSS_SELECTOR, "table.custom-table thead").text)

    # Extra safety wait: ensure the row cells actually have text content
    # (the table skeleton can appear before the API data populates it)
    wait.until(lambda d: len(d.find_element(By.CSS_SELECTOR, "table.custom-table tbody tr td").text.strip()) > 0)

    print("SUCCESS: P2P/P2M table loaded, elements found.")
    driver.save_screenshot("step4_table_loaded.png")


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

    print("Starting monthly data processing...")
    row_elements = driver.find_elements(By.CSS_SELECTOR, "table.custom-table tbody tr")
    print(f"Total rows found in table: {len(row_elements)}")

    # This page only ever shows a single row (the month/year selected via
    # the page's own dropdown filter, which defaults to the latest month) -
    # no top-row skipping or multi-row slicing is needed here.
    scraped_data_list = []

    for row in row_elements:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 6:
                print("Skip: row has fewer than 6 cells.")
                continue

            raw_month = cells[0].get_attribute("textContent").strip()
            raw_val = cells[5].get_attribute("textContent").strip()

            if not raw_month or not raw_val:
                print(f"Skip: empty month or value cell (month='{raw_month}', value='{raw_val}').")
                continue

            period_label = normalize_month_year(raw_month)
            if not period_label:
                print(f"Skip: could not normalize month text '{raw_month}'.")
                continue

            val = parse_value(raw_val)
            scraped_data_list.append({"period_label": period_label, "value": val})
        except Exception:
            continue

    valid_rows_count = 0
    failed_rows = []
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]

            valid_rows_count += 1
            print(f"\nProcessing Monthly Row {valid_rows_count} -> Month: {period_label}, Value: {value}")

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
            print(f"SUCCESS: New data for {period_label} inserted into '{DRAFT_TABLE}'.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            failed_rows.append({"period_label": item.get("period_label", "unknown"), "error": str(row_err)})
            continue

    print(f"\nScraping complete! Total {valid_rows_count} monthly rows processed.")

    if valid_rows_count == 0:
        print("CRITICAL: Not a single row was scraped - the site structure may have changed or selectors failed.")
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
