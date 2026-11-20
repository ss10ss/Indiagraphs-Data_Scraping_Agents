import time
import re
import sys
import calendar
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
# CONFIGURATION: Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"
DRAFT_TABLE = "data_points_draft"
MONTHLY_DATASET_ID = 199
ANNUAL_DATASET_ID = 230
MAX_NAV_ATTEMPTS = 3   # Number of full navigation retries (site load through table load)
MONTHS_TO_SCRAPE = 5
ANNUAL_ROWS_TO_CHECK = 3   # How many of the most recent FY rows to check for an Annual value

# Column index (as used in the site's 'c' attribute, 1=Apr ... 12=Mar) -> actual calendar month number
MONTH_COLUMN_TO_CALENDAR = {1: 4, 2: 5, 3: 6, 4: 7, 5: 8, 6: 9, 7: 10, 8: 11, 9: 12, 10: 1, 11: 2, 12: 3}
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


def parse_fy_start(fy_label):
    """
    Handles the format: '2026-27' -> 2026 (the fiscal year's starting calendar year)
    """
    try:
        parts = fy_label.strip().split('-')
        fy_start = int(parts[0].strip())
        return fy_start
    except Exception as e:
        print(f"Error parsing fiscal year label '{fy_label}': {e}")
        return None


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


def parse_fy_dates(period_label):
    """
    Handles the format: '2025-26' -> (2025-04-01, 2026-03-31)
    """
    try:
        parts = period_label.strip().split('-')
        if len(parts) != 2:
            return None, None

        fy_start = int(parts[0].strip())
        fy_end_short = parts[1].strip()

        if len(fy_end_short) == 2:
            fy_end = int(str(fy_start)[:2] + fy_end_short)
        else:
            fy_end = int(fy_end_short)

        start_date = f"{fy_start}-04-01"
        end_date = f"{fy_end}-03-31"

        return start_date, end_date
    except Exception as e:
        print(f"Error parsing FY date: {e}")
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
    Full flow from opening the site to the data table being loaded.
    Raises an Exception on failure at any step (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")

    print("Waiting explicitly for the page to settle...")
    time.sleep(12)
    driver.save_screenshot("step1_initial_page.png")

    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(3)
    except Exception:
        pass

    print("Entering 'sensex' in the search box...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("sensex")
    time.sleep(3)
    driver.save_screenshot("step2_search_text_entered.png")

    print("Selecting 'all of the words' from the dropdown...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select_filter = Select(dropdown_element)

    target_option = None
    for option in select_filter.options:
        option_text = (option.get_attribute("textContent") or "").strip().lower()
        if "all of the words" in option_text or "all these words" in option_text:
            target_option = option
            break

    if target_option is None:
        available = [opt.get_attribute("textContent").strip() for opt in select_filter.options]
        raise Exception(f"Could not find an 'all of the words' option in the dropdown. Available options: {available}")

    select_filter.select_by_value(target_option.get_attribute("value"))
    time.sleep(3)
    driver.save_screenshot("step3_dropdown_selected.png")

    print("Clicking the Update Results button...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    try:
        update_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", update_btn)
    time.sleep(15)
    driver.save_screenshot("step4_results_updated.png")

    print("Clicking the 'Monthly and Annual Averages of BSE SENSEX' link...")
    report_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space(text())='Monthly and Annual Averages of BSE SENSEX (Base : 1978-79 = 100)']")))

    main_window = driver.current_window_handle
    try:
        report_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", report_link)

    print("Link clicked. Waiting dynamically for the new tab to open...")
    wait.until(lambda d: len(d.window_handles) > 1)
    driver.save_screenshot("step5_link_clicked.png")

    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Successfully switched to the new tab.")
                break

    print("Waiting for the loading spinner to finish...")
    time.sleep(8)

    print("Locating and switching into the iframe...")
    iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
    driver.switch_to.frame(iframe_element)
    print("Successfully switched inside the data iframe.")

    print("Waiting for table elements to be validated...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//td[@bid='616']")))
    print("SUCCESS: Table loaded, elements found.")
    driver.save_screenshot("step6_data_tab_loaded.png")


def extract_cell_value(driver, bid, c, idref):
    """
    A value cell is normally a plain <td><span>. However, whichever cell is
    currently 'selected/highlighted' on the site renders differently (as an
    overlay div with no span in it) - in that case the value is pulled from
    its aria-label attribute instead.
    """
    try:
        val_elements = driver.find_elements(By.XPATH, f"//td[@bid='{bid}' and @c='{c}' and @idref='{idref}']//span")
        if val_elements:
            raw_val = val_elements[0].get_attribute("textContent").strip()
            if raw_val:
                return raw_val
    except Exception:
        pass

    try:
        overlay_elements = driver.find_elements(By.XPATH, f"//*[@data_roelement_idref='{idref}' and @aria-label]")
        for el in overlay_elements:
            aria_label = el.get_attribute("aria-label") or ""
            match = re.search(r"([\d,]+\.\d+|-)\.\s*Row", aria_label)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None


def get_fy_label_for_suffix(driver, suffix):
    """
    Reads the fiscal-year row label (e.g. '2026-27') for a given row suffix.
    """
    try:
        year_elements = driver.find_elements(By.XPATH, f"//td[@bid='616' and @idref='9Z.9e.{suffix}']//span")
        if year_elements:
            return (year_elements[0].get_attribute("textContent") or "").replace(' ', '').strip()
    except Exception:
        pass
    return None


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

    # =====================================================================
    # PART 1: Monthly average (dataset_id 199) - last MONTHS_TO_SCRAPE months,
    # pulled from the current fiscal-year row and, if that row doesn't have
    # enough completed months yet, carried over from the previous FY row.
    # =====================================================================
    print("\n=== Processing Monthly Average (dataset_id 199) ===")

    fy_label_0 = get_fy_label_for_suffix(driver, 0)
    fy_label_1 = get_fy_label_for_suffix(driver, 1)
    print(f"Current FY row label: {fy_label_0}")
    print(f"Previous FY row label: {fy_label_1}")

    fy_start_0 = parse_fy_start(fy_label_0) if fy_label_0 else None
    fy_start_1 = parse_fy_start(fy_label_1) if fy_label_1 else None

    chronological_months = []

    # Previous FY row first (older), then current FY row (newer) - this keeps
    # the assembled list in true chronological (oldest-to-newest) order.
    for suffix, fy_start in [(1, fy_start_1), (0, fy_start_0)]:
        if fy_start is None:
            continue
        for col in range(1, 13):
            idref = f"9Z.9f.{col}.{suffix}"
            raw_val = extract_cell_value(driver, "617", col, idref)
            if not raw_val or raw_val.strip() == "-":
                continue
            calendar_month = MONTH_COLUMN_TO_CALENDAR[col]
            target_year = fy_start if col <= 9 else fy_start + 1
            period_label = f"{calendar.month_abbr[calendar_month]} {target_year}"
            try:
                value = float(raw_val.replace(',', '').strip())
            except Exception:
                continue
            chronological_months.append({"period_label": period_label, "value": value})

    last_n_months = chronological_months[-MONTHS_TO_SCRAPE:]
    print(f"Months available after assembly: {len(chronological_months)}, taking last {len(last_n_months)}.")

    monthly_valid_count = 0
    monthly_failed = []
    for item in last_n_months:
        try:
            period_label = item["period_label"]
            value = item["value"]

            print(f"\nProcessing Monthly -> Month: {period_label}, Value: {value}")

            if period_exists(CHECK_TABLE, MONTHLY_DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}'.")
                continue
            if period_exists(DRAFT_TABLE, MONTHLY_DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}'.")
                continue

            print(f"'{period_label}' is absent from both tables. Inserting new record into '{DRAFT_TABLE}'...")
            period_start, period_end = parse_monthly_dates(period_label)

            data_to_insert = {
                "dataset_id": MONTHLY_DATASET_ID,
                "period_type": "MONTH",
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "is_active": False,
                "created_by": "c7dcaab6-1312-4d08-8b39-d327827d885f"
            }
            supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
            monthly_valid_count += 1
            print(f"SUCCESS: New data for {period_label} inserted into '{DRAFT_TABLE}'.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            monthly_failed.append({"period_label": item.get("period_label", "unknown"), "error": str(row_err)})
            continue

    print(f"\nMonthly scraping complete! {monthly_valid_count} new row(s) inserted.")

    # =====================================================================
    # PART 2: Annual average (dataset_id 230) - checks the most recent FY
    # rows; a row whose Annual column still shows '-' (fiscal year not yet
    # complete) is skipped until a real value appears on a future run.
    # =====================================================================
    print("\n=== Processing Annual Average (dataset_id 230) ===")

    annual_valid_count = 0
    annual_failed = []
    for suffix in range(ANNUAL_ROWS_TO_CHECK):
        fy_label = None
        try:
            fy_label = get_fy_label_for_suffix(driver, suffix)
            if not fy_label:
                print(f"Skip (row suffix {suffix}): no fiscal year label found.")
                continue

            idref = f"9Z.9-.{suffix}"
            raw_val = extract_cell_value(driver, "639", "13", idref)

            if not raw_val or raw_val.strip() == "-":
                print(f"Skip: Annual average for '{fy_label}' is not yet available ('-').")
                continue

            value = float(raw_val.replace(',', '').strip())
            print(f"\nProcessing Annual -> FY: {fy_label}, Value: {value}")

            if period_exists(CHECK_TABLE, ANNUAL_DATASET_ID, fy_label):
                print(f"Skip: '{fy_label}' already exists in '{CHECK_TABLE}'.")
                continue
            if period_exists(DRAFT_TABLE, ANNUAL_DATASET_ID, fy_label):
                print(f"Skip: '{fy_label}' already exists in '{DRAFT_TABLE}'.")
                continue

            print(f"'{fy_label}' is absent from both tables. Inserting new record into '{DRAFT_TABLE}'...")
            period_start, period_end = parse_fy_dates(fy_label)

            data_to_insert = {
                "dataset_id": ANNUAL_DATASET_ID,
                "period_type": "FY",
                "period_label": fy_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "is_active": False,
                "created_by": "c7dcaab6-1312-4d08-8b39-d327827d885f"
            }
            supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
            annual_valid_count += 1
            print(f"SUCCESS: New data for {fy_label} inserted into '{DRAFT_TABLE}'.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            annual_failed.append({"period_label": fy_label or "unknown", "error": str(row_err)})
            continue

    print(f"\nAnnual scraping complete! {annual_valid_count} new row(s) inserted.")

    total_failed = monthly_failed + annual_failed
    if total_failed:
        print(f"\nWARNING: {len(total_failed)} row(s) failed while processing:")
        for f in total_failed:
            print(f"  - {f['period_label']}: {f['error']}")
        sys.exit(1)

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
