"""
RBI Automation Generator
=========================
Reads a config (JSON) describing a new RBI scraper automation and produces
a matching .py scraper + .yml GitHub Actions workflow, following the
established pattern (retry logic, dedupe against data_points then
data_points_draft, screenshot steps, professional English comments).

Usage:
    python generate_automation.py my_config.json

Output:
    <file_name>.py
    <file_name>.yml
written into the same directory this script is run from.
"""

import json
import sys


YML_TEMPLATE = """name: {workflow_name}

on:
  schedule:
    - cron: '{cron}'   # {cron_comment}

  workflow_dispatch:

concurrency:
  group: {workflow_name}
  cancel-in-progress: false

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Chrome & Dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y google-chrome-stable
          python -m pip install --upgrade pip
          pip install selenium webdriver-manager supabase

      - name: Run Scraper Script
        env:
          SUPABASE_URL: ${{{{ secrets.SUPABASE_URL }}}}
          SUPABASE_KEY: ${{{{ secrets.SUPABASE_KEY }}}}
        run: |
          cd Agents
          python {file_name}.py

      - name: Upload Debug Screenshots
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: {artifact_name}
          path: Agents/step*.png
"""


PY_HEADER = '''import time
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
CHECK_TABLE = "{check_table}"
DRAFT_TABLE = "{draft_table}"
DATASET_ID = {dataset_id}
MAX_NAV_ATTEMPTS = 3   # Number of full navigation retries (site load through table load)
ROWS_TO_SCRAPE = {rows_to_scrape}
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


def parse_period_dates(period_label):
    """
    Handles the format: 'Mar 2026' -> (2026-03-01, 2026-03-31)
    Extend this if a non-MONTH period_type is ever needed.
    """
    try:
        parts = period_label.strip().split()
        if len(parts) != 2:
            return None, None

        month_str, year_str = parts[0].title(), parts[1]
        month_modules = {{v: k for k, v in enumerate(calendar.month_abbr)}}
        month_num = month_modules.get(month_str[:3])

        if not month_num:
            month_modules_full = {{v: k for k, v in enumerate(calendar.month_name)}}
            month_num = month_modules_full.get(month_str)

        if not month_num:
            return None, None

        year = int(year_str)
        start_date = f"{{year}}-{{month_num:02d}}-01"
        last_day = calendar.monthrange(year, month_num)[1]
        end_date = f"{{year}}-{{month_num:02d}}-{{last_day:02d}}"

        return start_date, end_date
    except Exception as e:
        print(f"Error parsing period date: {{e}}")
        return None, None


{conversion_function}

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

    print("Entering '{search_text}' in the search box...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("{search_text}")
    time.sleep(3)
    driver.save_screenshot("step2_search_text_entered.png")

    print("Selecting '{dropdown_filter}' from the dropdown...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select_filter = Select(dropdown_element)

    target_option = None
    for option in select_filter.options:
        option_text = (option.get_attribute("textContent") or "").strip().lower()
        if "{dropdown_filter_lower}" in option_text:
            target_option = option
            break

    if target_option is None:
        available = [opt.get_attribute("textContent").strip() for opt in select_filter.options]
        raise Exception(f"Could not find a '{dropdown_filter}' option in the dropdown. Available options: {{available}}")

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

    print("Clicking the '{report_link_text}' link...")
    report_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), '{report_link_text}')]")))

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
{new_format_block}
    print("Waiting for table elements to be validated...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//td[@bid='{month_bid}']")))
    print("SUCCESS: Table loaded, elements found.")
    driver.save_screenshot("step6_data_tab_loaded.png")

'''


NEW_FORMAT_BLOCK = '''
    print("Selecting the 'New Format' tab...")
    try:
        new_format_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@title='New Format']")))
        driver.execute_script("arguments[0].click();", new_format_tab)
        time.sleep(4)
    except Exception as e:
        print(f"Issue clicking the 'New Format' tab (it may already be selected): {e}")
    driver.save_screenshot("step5b_new_format_selected.png")
'''


CONVERSION_FUNCTIONS = {
    "none": '''def convert_value(raw_val):
    """No unit conversion needed - value is stored as scraped."""
    return float(raw_val.replace(',', '').strip())

''',
    "decimal_shift_left_1": '''def convert_value(raw_val):
    """
    Shifts the decimal point one place to the left directly on the digit
    string (e.g. Lakh -> Million). No floating-point division is used, so
    there are no binary floating-point rounding artifacts.
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

''',
    "round_int": '''def convert_value(raw_val):
    """Rounds the scraped value to the nearest whole number."""
    return int(round(float(raw_val.replace(',', '').strip())))

''',
}


# ---- Extraction-mode bodies (how rows get pulled out of the table) ----

BODY_SIMPLE = '''    print("Starting monthly data processing...")
    table_rows = driver.find_elements(By.XPATH, "//tr[td[@bid='{month_bid}']]")

    scraped_data_list = []

    for row in table_rows:
        try:
            month_elements = row.find_elements(By.XPATH, ".//td[@bid='{month_bid}']//span")
            val_elements = row.find_elements(By.XPATH, ".//td[@bid='{value_bid}']//span")

            if month_elements and val_elements:
                raw_month = month_elements[0].get_attribute("textContent").strip()
                raw_val = val_elements[0].get_attribute("textContent").strip()

                if raw_month and raw_val:
                    full_period_label = raw_month.replace('-', ' ').strip().title()
                    val = convert_value(raw_val)
                    scraped_data_list.append({{"period_label": full_period_label, "value": val}})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:ROWS_TO_SCRAPE]
    scraped_data_list.reverse()
'''

HELPER_IDREF_SUFFIX = '''def extract_value_for_suffix(driver, suffix):
    """
    The value cell (bid={value_bid}) is normally a plain <td><span>.
    However, whichever cell is currently 'selected/highlighted' on the site
    renders differently (as an overlay div with no span in it) - in that
    case the value is pulled from its aria-label attribute instead.
    """
    idref = f"{value_idref_prefix}.{{suffix}}"

    # Normal case: plain td > span
    try:
        val_elements = driver.find_elements(By.XPATH, f"//td[@bid='{value_bid}' and @idref='{{idref}}']//span")
        if val_elements:
            raw_val = val_elements[0].get_attribute("textContent").strip()
            if raw_val:
                return raw_val
    except Exception:
        pass

    # Fallback case: selected/highlighted overlay cell -> value is in aria-label
    try:
        overlay_elements = driver.find_elements(By.XPATH, f"//*[@data_roelement_idref='{{idref}}' and @aria-label]")
        for el in overlay_elements:
            aria_label = el.get_attribute("aria-label") or ""
            match = re.search(r"([\\d,]+\\.\\d+)\\.\\s*Row", aria_label)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None

'''

BODY_IDREF_SUFFIX = '''    print("Starting monthly data processing...")
    try:
        wait.until(lambda d: len(d.find_elements(By.XPATH, "//td[@bid='{month_bid}']")) >= ROWS_TO_SCRAPE)
    except Exception:
        print(f"WARNING: Fewer than {{ROWS_TO_SCRAPE}} month cells found even after waiting; proceeding with whatever is available.")
    month_cells = driver.find_elements(By.XPATH, "//td[@bid='{month_bid}']")
    print(f"Total month cells found: {{len(month_cells)}}")

    scraped_data_list = []

    for cell in month_cells:
        try:
            idref = cell.get_attribute("idref") or ""
            suffix = idref.split(".")[-1] if idref else None
            if suffix is None or not suffix.isdigit():
                continue

            month_span = cell.find_elements(By.XPATH, ".//span")
            if not month_span:
                print(f"Skip (suffix {{suffix}}): no month span found - row may be unrendered.")
                continue
            raw_month = month_span[0].get_attribute("textContent").strip()
            if not raw_month:
                print(f"Skip (suffix {{suffix}}): month text is empty.")
                continue

            raw_val = extract_value_for_suffix(driver, suffix)
            if not raw_val:
                print(f"Skip (suffix {{suffix}}, month {{raw_month}}): value not found (neither td span nor overlay).")
                continue

            full_period_label = raw_month.replace('-', ' ').strip().title()
            val = convert_value(raw_val)
            scraped_data_list.append({{"period_label": full_period_label, "value": val}})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:ROWS_TO_SCRAPE]
    scraped_data_list.reverse()
'''

BODY_FISCAL_YEAR = '''    print("Starting monthly data processing...")
    table_rows = driver.find_elements(By.XPATH, "//tr[th[@bid='{fy_header_bid}'] or td[@bid='{month_bid}']]")

    scraped_data_list = []
    current_fy = None

    for row in table_rows:
        try:
            year_headers = row.find_elements(By.XPATH, "./th[@bid='{fy_header_bid}']//span")
            if year_headers:
                current_fy = year_headers[0].get_attribute("textContent").strip()
                continue

            month_elements = row.find_elements(By.XPATH, "./td[@bid='{month_bid}' and @c='0']//span")
            val_elements = row.find_elements(By.XPATH, "./td[@bid='{value_bid}' and @c='{value_c}']//span")

            if month_elements and val_elements and current_fy:
                raw_month = month_elements[0].get_attribute("textContent").strip().title()
                raw_val = val_elements[0].get_attribute("textContent").strip()

                if raw_month and raw_val:
                    fy_start = int(current_fy.split('-')[0].strip())
                    fy_end = int(current_fy.split('-')[1].strip())
                    if len(str(fy_end)) == 2:
                        fy_end = int(str(fy_start)[:2] + str(fy_end))

                    target_year = fy_end if raw_month.upper() in ["JAN", "FEB", "MAR"] else fy_start
                    full_period_label = f"{{raw_month}} {{target_year}}"

                    val = convert_value(raw_val)
                    scraped_data_list.append({{"period_label": full_period_label, "value": val}})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:ROWS_TO_SCRAPE]
    scraped_data_list.reverse()
'''


PY_FOOTER = '''
    valid_rows_count = 0
    failed_rows = []
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]

            valid_rows_count += 1
            print(f"\\nProcessing Row {valid_rows_count} -> Period: {period_label}, Value: {value}")

            # Step 1: Check if this period_label already exists in CHECK_TABLE (data_points)
            check_response = supabase.table(CHECK_TABLE).select("period_label").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            exists_in_check = len(check_response.data) > 0

            if exists_in_check:
                print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}'.")
                continue

            # Step 2: Not found in CHECK_TABLE, now check DRAFT_TABLE (data_points_draft) too
            draft_response = supabase.table(DRAFT_TABLE).select("period_label").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            exists_in_draft = len(draft_response.data) > 0

            if exists_in_draft:
                print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}'.")
                continue

            # Step 3: Not found in either table - genuinely new data, insert into DRAFT_TABLE
            print(f"'{period_label}' is absent from both tables. Inserting new record into '{DRAFT_TABLE}'...")
            period_start, period_end = parse_period_dates(period_label)

            data_to_insert = {
                "dataset_id": DATASET_ID,
                "period_type": "PERIOD_TYPE_PLACEHOLDER",
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "is_active": False,
                "created_by": "CREATED_BY_PLACEHOLDER"
            }

            insert_resp = supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
            print(f"SUCCESS: New data for {period_label} inserted into '{DRAFT_TABLE}'.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            failed_rows.append({"period_label": item.get("period_label", "unknown"), "error": str(row_err)})
            continue

    print(f"\\nScraping complete! Total {valid_rows_count} rows processed.")

    if valid_rows_count == 0:
        print("CRITICAL: Not a single row was scraped - the site structure may have changed or selectors failed.")
        sys.exit(1)

    if failed_rows:
        print(f"\\nWARNING: {len(failed_rows)} row(s) failed while processing:")
        for f in failed_rows:
            print(f"  - {f['period_label']}: {f['error']}")
        sys.exit(1)

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
'''


PY_MAIN_WRAPPER_TOP = '''driver, wait = create_driver()

try:
    # ---- Run the full navigation flow with retries ----
    navigation_success = False
    for attempt in range(1, MAX_NAV_ATTEMPTS + 1):
        try:
            print(f"\\n--- Navigation attempt {attempt}/{MAX_NAV_ATTEMPTS} ---")
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

'''


def build_yml(cfg):
    job_id = cfg["file_name"].split("_", 1)[-1].replace("_", "-")
    artifact_name = cfg.get("artifact_name", f"{job_id}-step-screenshots")
    cron_comment = cfg.get(
        "cron_comment",
        "Runs daily within the scrape window - retries until the data is published"
    )
    return YML_TEMPLATE.format(
        workflow_name=cfg["workflow_name"],
        cron=cfg["cron"],
        cron_comment=cron_comment,
        job_id=job_id,
        file_name=cfg["file_name"],
        artifact_name=artifact_name,
    )


def build_py(cfg):
    conversion = CONVERSION_FUNCTIONS[cfg["conversion"]]

    new_format_block = NEW_FORMAT_BLOCK if cfg.get("requires_new_format_tab") else ""

    header = PY_HEADER.format(
        check_table=cfg.get("check_table", "data_points"),
        draft_table=cfg.get("draft_table", "data_points_draft"),
        dataset_id=cfg["dataset_id"],
        rows_to_scrape=cfg.get("rows_to_scrape", 5),
        conversion_function=conversion,
        search_text=cfg["search_text"],
        dropdown_filter=cfg["dropdown_filter"],
        dropdown_filter_lower=cfg["dropdown_filter"].lower(),
        report_link_text=cfg["report_link_text"],
        new_format_block=new_format_block,
        month_bid=cfg["month_bid"],
    )

    mode = cfg["extraction_mode"]
    helper = ""
    if mode == "simple":
        body = BODY_SIMPLE.format(month_bid=cfg["month_bid"], value_bid=cfg["value_bid"])
    elif mode == "idref_suffix":
        helper = HELPER_IDREF_SUFFIX.format(
            value_bid=cfg["value_bid"],
            value_idref_prefix=cfg["value_idref_prefix"],
        )
        body = BODY_IDREF_SUFFIX.format(month_bid=cfg["month_bid"])
    elif mode == "fiscal_year":
        body = BODY_FISCAL_YEAR.format(
            fy_header_bid=cfg["fy_header_bid"],
            month_bid=cfg["month_bid"],
            value_bid=cfg["value_bid"],
            value_c=cfg["value_c"],
        )
    else:
        raise ValueError(f"Unknown extraction_mode: {mode}")

    footer = PY_FOOTER.replace(
        "PERIOD_TYPE_PLACEHOLDER", cfg.get("period_type", "MONTH")
    ).replace(
        "CREATED_BY_PLACEHOLDER", cfg.get("created_by", "c7dcaab6-1312-4d08-8b39-d327827d885f")
    )

    return header + PY_MAIN_WRAPPER_TOP + body + footer


def main():
    if len(sys.argv) != 2:
        print("Usage: python generate_automation.py <config.json>")
        sys.exit(1)

    with open(sys.argv[1], "r") as f:
        cfg = json.load(f)

    py_content = build_py(cfg)
    yml_content = build_yml(cfg)

    py_path = f"{cfg['file_name']}.py"
    yml_path = f"{cfg['file_name']}.yml"

    with open(py_path, "w") as f:
        f.write(py_content)
    with open(yml_path, "w") as f:
        f.write(yml_content)

    print(f"Generated: {py_path}")
    print(f"Generated: {yml_path}")


if __name__ == "__main__":
    main()
