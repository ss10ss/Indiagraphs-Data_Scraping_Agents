import time
import re
import sys
from datetime import datetime
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
DATASET_ID = 77
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


def convert_lakh_to_million(raw_val):
    """
    The site reports the Volume figure in Lakh; Supabase stores it in Million.
    1 Lakh = 0.1 Million, so this shifts the decimal point one place to the
    left directly on the digit string (no floating-point division), which
    avoids binary floating-point rounding artifacts entirely.
    e.g. '2,56,317.02' -> '256317.02' -> '25631.702'
    """
    cleaned = raw_val.replace(',', '').strip()

    if '.' in cleaned:
        integer_part, decimal_part = cleaned.split('.')
    else:
        integer_part, decimal_part = cleaned, ''

    if not integer_part:
        integer_part = '0'

    moved_digit = integer_part[-1]
    new_integer_part = integer_part[:-1] or '0'
    new_decimal_part = moved_digit + decimal_part

    return float(f"{new_integer_part}.{new_decimal_part}")


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

    print("Entering 'digital payments' in the search box...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("digital payments")
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

    print("Clicking the 'Payment System Indicators' link...")
    report_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Payment System Indicators')]")))

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

    print("Selecting the 'New Format' tab...")
    new_format_selected = False
    for tab_attempt in range(1, 4):
        try:
            new_format_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@title='New Format']")))
            driver.execute_script("arguments[0].click();", new_format_tab)
            time.sleep(3)
            tab_class = new_format_tab.get_attribute("class") or ""
            if "sapMTabStripItemSelected" in tab_class:
                new_format_selected = True
                print(f"'New Format' tab confirmed selected (attempt {tab_attempt}).")
                break
            print(f"'New Format' tab click attempt {tab_attempt} did not register as selected, retrying...")
        except Exception as e:
            print(f"'New Format' tab click attempt {tab_attempt} raised an error: {e}")
        time.sleep(2)

    driver.save_screenshot("step5b_new_format_selected.png")

    if not new_format_selected:
        raise Exception("Could not confirm 'New Format' tab got selected after retries - table would load in Old Format layout.")

    print("Waiting for table elements to be validated...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//td[@bid='984']")))
    print("SUCCESS: Table loaded, elements found.")
    driver.save_screenshot("step6_data_tab_loaded.png")


def extract_value_for_suffix(driver, suffix):
    """
    The value cell (bid=893) is normally a plain <td><span>.
    However, whichever cell is currently 'selected/highlighted' on the site
    renders differently (as an overlay div with no span in it) - in that
    case the value is pulled from its aria-label attribute instead.
    """
    idref = f"2.Dz.u.{suffix}"

    # Normal case: plain td > span
    try:
        val_elements = driver.find_elements(By.XPATH, f"//td[@bid='893' and @idref='{idref}']//span")
        if val_elements:
            raw_val = val_elements[0].get_attribute("textContent").strip()
            if raw_val:
                return raw_val
    except Exception:
        pass

    # Fallback case: selected/highlighted overlay cell -> value is in aria-label
    try:
        overlay_elements = driver.find_elements(By.XPATH, f"//*[@data_roelement_idref='{idref}' and @aria-label]")
        for el in overlay_elements:
            aria_label = el.get_attribute("aria-label") or ""
            match = re.search(r"([\d,]+\.\d+)\.\s*Row", aria_label)
            if match:
                return match.group(1)
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

    print("Starting monthly data processing...")
    try:
        wait.until(lambda d: len(d.find_elements(By.XPATH, "//td[@bid='984']")) >= 5)
    except Exception:
        print("WARNING: Fewer than 5 month cells found even after waiting; proceeding with whatever is available.")
    month_cells = driver.find_elements(By.XPATH, "//td[@bid='984']")
    print(f"Total month cells found: {len(month_cells)}")

    scraped_data_list = []

    for cell in month_cells:
        try:
            idref = cell.get_attribute("idref") or ""
            suffix = idref.split(".")[-1] if idref else None
            if suffix is None or not suffix.isdigit():
                continue

            month_span = cell.find_elements(By.XPATH, ".//span")
            if not month_span:
                print(f"Skip (suffix {suffix}): no month span found - row may be unrendered.")
                continue
            raw_month = month_span[0].get_attribute("textContent").strip()
            if not raw_month:
                print(f"Skip (suffix {suffix}): month text is empty.")
                continue

            raw_val = extract_value_for_suffix(driver, suffix)
            if not raw_val:
                print(f"Skip (suffix {suffix}, month {raw_month}): value not found (neither td span nor overlay).")
                continue

            full_period_label = raw_month.replace('-', ' ').strip().title()
            val = convert_lakh_to_million(raw_val)
            scraped_data_list.append({"period_label": full_period_label, "value": val})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:5]
    scraped_data_list.reverse()

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
