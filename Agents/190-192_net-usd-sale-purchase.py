import calendar
import os
import re
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from supabase import Client, create_client
from webdriver_manager.chrome import ChromeDriverManager

# =====================================================================
# Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"
DRAFT_TABLE = "data_points_draft"
MAX_NAV_ATTEMPTS = 3
CREATED_BY = "c7dcaab6-1312-4d08-8b39-d327827d885f"
DATASET_CONFIGS = [
    {
        "dataset_id": 190,
        "dataset_name": "Net USD sale/purchase",
        "idref_prefix": "U.EO.0",
    },
    {
        "dataset_id": 191,
        "dataset_name": "Net USD purchase",
        "idref_prefix": "U.EO.1",
    },
    {
        "dataset_id": 192,
        "dataset_name": "Net USD sale",
        "idref_prefix": "U.EO.2",
    },
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
chrome_options.page_load_strategy = "eager"

# Automation detection bypass
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

chrome_options.add_argument("--window-size=1366,768")
chrome_options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def create_driver():
    d = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )
    d.set_page_load_timeout(90)
    w = WebDriverWait(d, 60)
    return d, w


def normalize_month_to_abbr(raw_month):
    """
    This site reports the month as a FULL name (e.g. 'June', 'April'),
    but Supabase period_label needs the abbreviated 3-letter form
    (e.g. 'Jun', 'Apr') to stay consistent with other monthly datasets.
    """
    raw_clean = raw_month.strip().title()

    full_to_abbr = {calendar.month_name[i]: calendar.month_abbr[i] for i in range(1, 13)}
    if raw_clean in full_to_abbr:
        return full_to_abbr[raw_clean]

    # Already abbreviated (defensive fallback, in case site format changes)
    valid_abbrs = [a for a in calendar.month_abbr if a]
    if raw_clean in valid_abbrs:
        return raw_clean

    # Last resort: just take the first 3 letters
    return raw_clean[:3]


def parse_monthly_dates(period_label):
    """
    Handles the format: 'Jun 2026' -> (2026-06-01, 2026-06-30)
    """
    try:
        parts = period_label.strip().split()
        if len(parts) != 2:
            return None, None

        month_str, year_str = parts[0].title(), parts[1]
        month_lookup = {v: k for k, v in enumerate(calendar.month_abbr)}
        month_num = month_lookup.get(month_str[:3])

        if not month_num:
            full_month_lookup = {v: k for k, v in enumerate(calendar.month_name)}
            month_num = full_month_lookup.get(month_str)

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
    response = (
        supabase.table(table_name)
        .select("period_label")
        .eq("dataset_id", dataset_id)
        .eq("period_label", period_label)
        .execute()
    )
    if len(response.data) > 0:
        return True

    all_records = (
        supabase.table(table_name)
        .select("period_label")
        .eq("dataset_id", dataset_id)
        .execute()
    )
    normalized_target = period_label.replace("–", "-").strip()
    for rec in all_records.data:
        db_label = rec.get("period_label", "").replace("–", "-").strip()
        if db_label == normalized_target:
            return True
    return False


def parse_value(raw_val):
    """
    RBI reports these series in US $ Millions (with 2 decimal places, e.g.
    '561.00' or '-6104.00'), and Supabase stores them in the same unit - no
    conversion needed. The '-' sign is preserved as-is (Net Sale values can
    legitimately be negative).
    e.g. '-6104.00' -> -6104.0
    """
    cleaned = raw_val.replace(",", "").strip()
    return int(cleaned) if "." not in cleaned else float(cleaned)


def navigate_to_table(driver, wait):
    """
    Full flow from opening the RBI DBIE site to the Sale/Purchase of U.S.
    Dollar by the RBI table being loaded.
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

    print("Entering 'Purchase of U.S. Dollar' in the search box...")
    search_box = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//input[@type='search' or @placeholder='Search']")
        )
    )
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("Purchase of U.S. Dollar")
    time.sleep(3)
    driver.save_screenshot("step2_search_text_entered.png")

    print("Selecting 'all of the words' from the dropdown...")
    dropdown_element = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown"))
    )
    select_filter = Select(dropdown_element)

    target_option = None
    for option in select_filter.options:
        option_text = (option.get_attribute("textContent") or "").strip().lower()
        if "all of the words" in option_text or "all these words" in option_text:
            target_option = option
            break

    if target_option is None:
        available = [
            opt.get_attribute("textContent").strip() for opt in select_filter.options
        ]
        raise Exception(
            "Could not find an 'all of the words' option in the dropdown. "
            f"Available options: {available}"
        )

    select_filter.select_by_value(target_option.get_attribute("value"))
    time.sleep(3)
    driver.save_screenshot("step3_dropdown_selected.png")

    print("Clicking the Update Results button...")
    update_btn = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button"))
    )
    try:
        update_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", update_btn)
    time.sleep(15)
    driver.save_screenshot("step4_results_updated.png")

    print("Clicking the 'Sale/ Purchase of U.S. Dollar by the RBI' link...")
    report_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(), 'Sale/ Purchase of U.S. Dollar by the RBI')]")
        )
    )

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
    iframe_element = wait.until(
        EC.presence_of_element_located((By.XPATH, "//iframe | //frame"))
    )
    driver.switch_to.frame(iframe_element)
    print("Successfully switched inside the data iframe.")

    # NOTE: The default/first tab ('Sale/Purchase of USD by R...') already
    # shows the required table - no extra tab click needed.
    print("Waiting for table elements to be validated...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//td[@bid='926']")))
    print("SUCCESS: Table loaded, elements found.")
    driver.save_screenshot("step6_data_tab_loaded.png")


def read_periods(driver):
    """
    Read the available month/year row keys once. These row keys are shared by
    all three Sale/Purchase component columns in the same table.
    Returns a list of dictionaries containing suffix and period_label.
    """
    print("Starting monthly row-key processing...")
    try:
        wait.until(
            lambda d: len(d.find_elements(By.XPATH, "//td[@bid='926']")) >= 5
        )
    except Exception:
        print(
            "WARNING: Fewer than 5 month cells found even after waiting; "
            "proceeding with whatever is available."
        )

    month_cells = driver.find_elements(By.XPATH, "//td[@bid='926']")
    print(f"Total month cells found: {len(month_cells)}")

    periods = []
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

            # Fetch the corresponding year cell for this suffix.
            year_elements = driver.find_elements(
                By.XPATH,
                f"//td[@bid='931' and @idref='U.EZ.{suffix}']//span",
            )
            if not year_elements:
                print(f"Skip (suffix {suffix}): year cell not found.")
                continue

            year = year_elements[0].get_attribute("textContent").strip()
            if not year:
                print(f"Skip (suffix {suffix}): year text is empty.")
                continue

            month_abbr = normalize_month_to_abbr(raw_month)
            periods.append(
                {
                    "suffix": suffix,
                    "period_label": f"{month_abbr} {year}",
                }
            )
        except Exception as e:
            print(f"Skip month cell while reading row keys: {e}")
            continue

    return periods


def extract_value_for_suffix(driver, config, suffix):
    """
    The value cell (bid=920) is normally a plain <td><span>.
    However, whichever cell is currently 'selected/highlighted' on the site
    renders differently (as an overlay div with no span in it) - in that
    case the value is pulled from its aria-label attribute instead.
    """
    idref = f"{config['idref_prefix']}.{suffix}"

    # Normal case: plain td > span
    try:
        val_elements = driver.find_elements(
            By.XPATH,
            f"//td[@bid='920' and @idref='{idref}']//span",
        )
        if val_elements:
            raw_val = val_elements[0].get_attribute("textContent").strip()
            if raw_val:
                return raw_val
    except Exception:
        pass

    # Fallback case: selected/highlighted overlay cell -> value is in aria-label
    # (allows an optional leading '-' since Net Sale values can be negative)
    try:
        overlay_elements = driver.find_elements(
            By.XPATH,
            f"//*[@data_roelement_idref='{idref}' and @aria-label]",
        )
        for el in overlay_elements:
            aria_label = el.get_attribute("aria-label") or ""
            match = re.search(r"(-?[\d,]+\.\d+)\.\s*Row", aria_label)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None


def scrape_dataset(driver, config, periods):
    """
    Extract the latest five available monthly values for one Sale/Purchase
    component.
    Returns (scraped_rows, extraction_failures).
    """
    dataset_id = config["dataset_id"]

    print("\n" + "=" * 72)
    print(f"Dataset {dataset_id}: {config['dataset_name']}")
    print("=" * 72)

    scraped_rows = []
    extraction_failures = []

    # Match the standalone scrapers: latest five displayed months, oldest first.
    for period in periods[:5][::-1]:
        suffix = period["suffix"]
        period_label = period["period_label"]

        try:
            raw_val = extract_value_for_suffix(driver, config, suffix)
            if not raw_val:
                failure = {
                    "period_label": period_label,
                    "error": "Value not found (neither td span nor overlay).",
                }
                extraction_failures.append(failure)
                print(
                    f"Skip (dataset {dataset_id}, suffix {suffix}, "
                    f"{period_label}): value not found."
                )
                continue

            val = parse_value(raw_val)
            scraped_rows.append({"period_label": period_label, "value": val})
        except Exception as e:
            failure = {"period_label": period_label, "error": str(e)}
            extraction_failures.append(failure)
            print(f"Skip (dataset {dataset_id}, {period_label}): {e}")
            continue

    print(f"Dataset {dataset_id}: {len(scraped_rows)} monthly value(s) extracted.")
    return scraped_rows, extraction_failures


def insert_new_dataset_rows(config, scraped_rows):
    """
    Insert only periods absent from both the checked and draft tables.
    Returns (inserted_count, processing_failures).
    """
    dataset_id = config["dataset_id"]

    if not scraped_rows:
        return 0, [
            {
                "period_label": "NO_DATA",
                "error": "Not a single row was scraped - the site structure may have changed or selectors failed.",
            }
        ]

    inserted_count = 0
    processing_failures = []

    for item in scraped_rows:
        try:
            period_label = item["period_label"]
            value = item["value"]

            print(
                f"\nProcessing dataset {dataset_id} -> Month: "
                f"{period_label}, Value: {value}"
            )

            # Step 1: Check if this period_label already exists in CHECK_TABLE.
            if period_exists(CHECK_TABLE, dataset_id, period_label):
                print(f"Skip: '{period_label}' already exists in '{CHECK_TABLE}'.")
                continue

            # Step 2: Not found in CHECK_TABLE, now check DRAFT_TABLE too.
            if period_exists(DRAFT_TABLE, dataset_id, period_label):
                print(f"Skip: '{period_label}' already exists in '{DRAFT_TABLE}'.")
                continue

            # Step 3: Not found in either table - genuinely new data, insert into DRAFT_TABLE.
            print(
                f"'{period_label}' is absent from both tables. "
                f"Inserting into '{DRAFT_TABLE}'..."
            )
            period_start, period_end = parse_monthly_dates(period_label)

            data_to_insert = {
                "dataset_id": dataset_id,
                "period_type": "MONTH",
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "is_active": False,
                "created_by": CREATED_BY,
            }

            supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
            inserted_count += 1
            print(f"SUCCESS: New data for {period_label} inserted into '{DRAFT_TABLE}'.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            processing_failures.append(
                {
                    "period_label": item.get("period_label", "unknown"),
                    "error": str(row_err),
                }
            )
            continue

    print(
        f"Dataset {dataset_id} complete: {len(scraped_rows)} monthly row(s) processed, "
        f"{inserted_count} new row(s) inserted."
    )
    return inserted_count, processing_failures


driver, wait = create_driver()

try:
    # ---- Run the full RBI DBIE navigation flow once, with retries ----
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

    periods = read_periods(driver)

    total_extracted = 0
    total_inserted = 0
    all_failures = []

    # ---- Extract and insert all three Sale/Purchase components from the same table ----
    for config in DATASET_CONFIGS:
        scraped_rows, extraction_failures = scrape_dataset(driver, config, periods)
        inserted_count, processing_failures = insert_new_dataset_rows(
            config,
            scraped_rows,
        )

        total_extracted += len(scraped_rows)
        total_inserted += inserted_count

        for failure in extraction_failures + processing_failures:
            all_failures.append(
                {
                    "dataset_id": config["dataset_id"],
                    "dataset_name": config["dataset_name"],
                    **failure,
                }
            )

    print("\n" + "=" * 72)
    print("MERGED SCRAPE SUMMARY")
    print("=" * 72)
    for config in DATASET_CONFIGS:
        dataset_failures = [
            f for f in all_failures if f["dataset_id"] == config["dataset_id"]
        ]
        print(
            f"Dataset {config['dataset_id']} ({config['dataset_name']}): "
            f"{len(dataset_failures)} failure(s)"
        )
    print(f"Total monthly values extracted: {total_extracted}")
    print(f"Total new rows inserted: {total_inserted}")

    if total_extracted == 0:
        print(
            "CRITICAL: Not a single row was scraped - the site structure may "
            "have changed or selectors failed."
        )
        sys.exit(1)

    if all_failures:
        print(f"\nWARNING: {len(all_failures)} row/dataset operation(s) failed:")
        for failure in all_failures:
            print(
                f"  - Dataset {failure['dataset_id']} ({failure['dataset_name']}), "
                f"{failure['period_label']}: {failure['error']}"
            )
        sys.exit(1)

    print("SUCCESS: All three datasets were scraped and checked without failures.")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
