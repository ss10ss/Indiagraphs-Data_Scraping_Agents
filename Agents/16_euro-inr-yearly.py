import time
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
DATASET_ID = 16
MAX_NAV_ATTEMPTS = 3   # Poori navigation (site load se table tak) kitni baar retry ho
# =====================================================================

# Supabase Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Options Setup
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


def parse_yearly_dates(period_label):
    """
    Format handle karta hai: '2025-26' -> (2025-04-01, 2026-03-31)
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
        print(f"Yearly Date parse karne me error: {e}")
        return None, None


def navigate_to_table(driver, wait):
    """
    Site kholne se lekar data table load hone tak ka poora flow.
    Kisi bhi step pe fail hone par Exception raise karta hai (calling code retry karega).
    """
    print("Page open ho raha hai...")
    driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")

    print("Settle hone ke liye explicitly wait kar rahe hain...")
    time.sleep(12)
    driver.save_screenshot("step1_initial_page.png")

    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(3)
    except Exception:
        pass

    print("Search box me 'usd to inr' enter ho raha hai...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("usd to inr")
    time.sleep(3)
    driver.save_screenshot("step2_search_text_entered.png")

    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select_filter = Select(dropdown_element)
    select_filter.select_by_value("oneormorewords")
    time.sleep(3)
    driver.save_screenshot("step3_dropdown_selected.png")

    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    try:
        update_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", update_btn)
    time.sleep(15)
    driver.save_screenshot("step4_results_updated.png")

    print("4th link par click ho raha hai (Financial Year-Annual Average)...")
    all_links = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@class, 'repLink')]")))
    target_link = None
    for link in all_links:
        if "Financial Year-Annual Average" in link.text or "Financial Year" in link.text:
            target_link = link
            break
    if not target_link:
        raise Exception("4th link (Financial Year-Annual Average) nahi mila.")

    main_window = driver.current_window_handle
    try:
        target_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", target_link)

    print("Link click ho gaya. Naya tab open hone ka dynamic wait...")
    wait.until(lambda d: len(d.window_handles) > 1)
    driver.save_screenshot("step5_link_clicked.png")

    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Naye tab par switch successfully ho gaye.")
                break

    print("Loading spinner ke khatam hone ka explicit wait...")
    time.sleep(8)

    print("Iframe dhoondh kar switch kiya ja raha hai...")
    iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
    driver.switch_to.frame(iframe_element)
    print("Successfully switched inside data iframe.")

    print("Table elements validation loop shuru...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//*[@bid='25' or @bid='27']")))
    print("SUCCESS: Table load ho gayi, elements mil chuke hain.")
    driver.save_screenshot("step6_data_tab_loaded.png")


driver, wait = create_driver()

try:
    # ---- Poore navigation flow ko retry ke saath chalao ----
    navigation_success = False
    for attempt in range(1, MAX_NAV_ATTEMPTS + 1):
        try:
            print(f"\n--- Navigation attempt {attempt}/{MAX_NAV_ATTEMPTS} ---")
            navigate_to_table(driver, wait)
            navigation_success = True
            break
        except Exception as e:
            print(f"Navigation attempt {attempt} me error aaya: {e}")
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
        print("CRITICAL: Saare navigation attempts fail ho gaye.")
        sys.exit(1)

    print("Yearly Data processing shuru...")
    table_rows = driver.find_elements(By.XPATH, "//tr[td[@bid='25' and @c='0']]")

    scraped_data_list = []

    for row in table_rows:
        try:
            year_elements = row.find_elements(By.XPATH, "./td[@bid='25' and @c='0']//span")
            # Euro Average column: bid='27', c='9'
            val_elements = row.find_elements(By.XPATH, "./td[@bid='27' and @c='9']//span")

            if year_elements and val_elements:
                raw_year = year_elements[0].get_attribute("textContent").strip().replace('\u00a0', '').strip()
                raw_val = val_elements[0].get_attribute("textContent").strip()

                if raw_year and raw_val:
                    val = float(raw_val.replace(',', '').strip())
                    scraped_data_list.append({"period_label": raw_year, "value": val})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:3]
    scraped_data_list.reverse()

    valid_rows_count = 0
    failed_rows = []
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]

            valid_rows_count += 1
            print(f"\nProcessing Yearly Row {valid_rows_count} -> Year: {period_label}, Value: {value}")

            # Step 1: Check karo ki ye period_label CHECK_TABLE (data_points) me exist karta hai?
            check_response = supabase.table(CHECK_TABLE).select("period_label").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            exists_in_check = len(check_response.data) > 0

            if exists_in_check:
                print(f"Skip: '{period_label}' already '{CHECK_TABLE}' me maujood hai.")
                continue

            # Step 2: CHECK_TABLE me nahi mila, ab DRAFT_TABLE (data_points_draft) me bhi check karo
            draft_response = supabase.table(DRAFT_TABLE).select("period_label").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            exists_in_draft = len(draft_response.data) > 0

            if exists_in_draft:
                print(f"Skip: '{period_label}' already '{DRAFT_TABLE}' me maujood hai.")
                continue

            # Step 3: Dono tables me nahi mila - matlab genuinely naya data hai, DRAFT_TABLE me insert karo
            print(f"'{period_label}' dono tables me absent hai. '{DRAFT_TABLE}' me naya insert ho raha hai...")
            period_start, period_end = parse_yearly_dates(period_label)

            data_to_insert = {
                "dataset_id": DATASET_ID,
                "period_type": "FY",
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "is_active": False,
                "created_by": "c7dcaab6-1312-4d08-8b39-d327827d885f"
            }

            insert_resp = supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
            print(f"SUCCESS: Year {period_label} ka naya data '{DRAFT_TABLE}' me chala gaya.")

        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            failed_rows.append({"period_label": item.get("period_label", "unknown"), "error": str(row_err)})
            continue

    print(f"\nScraping complete! Total {valid_rows_count} yearly rows process ki gayi hain.")

    if valid_rows_count == 0:
        print("CRITICAL: Ek bhi row scrape nahi hui - site structure badal gayi ho sakti hai ya selectors fail hue.")
        sys.exit(1)

    if failed_rows:
        print(f"\nWARNING: {len(failed_rows)} row(s) process karte waqt fail hui:")
        for f in failed_rows:
            print(f"  - {f['period_label']}: {f['error']}")
        sys.exit(1)

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
