import time
import sys
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client

# =====================================================================
# CONFIGURATION: Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "data_points"   
DRAFT_TABLE = "data_points_draft"   
DATASET_ID = 1
MAX_NAV_ATTEMPTS = 3   # Poori navigation (site load se table tak) kitni baar retry ho
# =====================================================================

# Supabase Credentials
import os
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
    d.set_page_load_timeout(60)
    w = WebDriverWait(d, 45)
    return d, w


def parse_fy_dates(period_label):
    try:
        start_year = period_label.split('-')[0].strip()
        end_year_short = period_label.split('-')[1].strip()
        century = start_year[:2]
        end_year = f"{century}{end_year_short}"
        return f"{start_year}-04-01", f"{end_year}-03-31"
    except Exception as e:
        print(f"Date parse karne me error: {e}")
        return None, None


def period_exists(table_name, dataset_id, period_label):
    """
    Ek table me period_label check karta hai - direct match, aur en-dash/hyphen
    normalization ke saath safe fallback (jaisa purane code me tha).
    """
    response = supabase.table(table_name).select("period_label").eq("dataset_id", dataset_id).eq("period_label", period_label).execute()
    if len(response.data) > 0:
        return True

    # Direct match nahi mila - normalize karke (en-dash vs hyphen) dobara check karo
    all_records = supabase.table(table_name).select("period_label").eq("dataset_id", dataset_id).execute()
    for rec in all_records.data:
        db_label = rec.get("period_label", "").replace("–", "-").strip()
        if db_label == period_label:
            return True
    return False


def navigate_to_table(driver, wait):
    """
    Site kholne se lekar data table load hone tak ka poora flow.
    Kisi bhi step pe fail hone par Exception raise karta hai (calling code retry karega).
    """
    print("Page open ho raha hai...")
    driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    driver.save_screenshot("step1_initial_page.png")

    try:
        alert = driver.switch_to.alert
        alert.dismiss()
    except Exception:
        pass

    print("Search box me text enter ho raha hai...")
    search_box = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("gold average")

    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select = Select(dropdown_element)
    select.select_by_value("oneormorewords")

    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    driver.execute_script("arguments[0].click();", update_btn)

    print("Results reload hone ka wait kar rahe hain (Waiting for spinner to disappear)...")
    try:
        wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "loading-spinner")))
    except Exception:
        pass

    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    driver.save_screenshot("step4_results_updated.png")

    print("First link par click ho raha hai...")
    link_xpath = "//a[contains(text(), 'Gold and Silver - Yearly Average Price')]"
    first_link = wait.until(EC.element_to_be_clickable((By.XPATH, link_xpath)))

    main_window = driver.current_window_handle
    driver.execute_script("arguments[0].click();", first_link)

    print("Naye tab ke open hone ka wait ho raha hai...")
    wait.until(EC.number_of_windows_to_be(2))

    current_handles = driver.window_handles
    for handle in current_handles:
        if handle != main_window:
            driver.switch_to.window(handle)
            print("Naye tab par switch successfully ho gaye.")
            break

    print("Naye tab ke poora load hone ka wait ho raha hai...")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    driver.save_screenshot("step5_link_clicked.png")

    print("Iframe dhoondh kar switch kiya ja raha hai...")
    iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
    driver.switch_to.frame(iframe_element)

    print("Table rows load hone ka wait chal raha hai...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//td[@bid='76' or @bid='72']/ancestor::tr")))
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

    print("Aapke HTML structure ke mutabik data extract ho raha hai...")
    all_rows = driver.find_elements(By.XPATH, "//tr[./td[@bid='76']]")

    scraped_data_list = []
    for row in all_rows[:3]:
        try:
            p_label = row.find_element(By.XPATH, "./td[@bid='76']//span").get_attribute("textContent").replace("–", "-").strip()
            g_raw = row.find_element(By.XPATH, "./td[@bid='72']//span").get_attribute("textContent").strip()

            if p_label and g_raw and g_raw != "":
                val = int(round(float(g_raw.replace(',', '').strip())))
                scraped_data_list.append({"period_label": p_label, "value": val})
        except Exception as e:
            print(f"Raw parse error: {e}")
            continue

    scraped_data_list.reverse()

    valid_rows_count = 0
    failed_rows = []
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]

            valid_rows_count += 1
            print(f"\nProcessing Yearly Row {valid_rows_count} -> Year: {period_label}, Price: {value}")

            # Step 1: Check karo ki ye period_label CHECK_TABLE (data_points) me exist karta hai?
            if period_exists(CHECK_TABLE, DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already '{CHECK_TABLE}' me maujood hai.")
                continue

            # Step 2: CHECK_TABLE me nahi mila, ab DRAFT_TABLE (data_points_draft) me bhi check karo
            if period_exists(DRAFT_TABLE, DATASET_ID, period_label):
                print(f"Skip: '{period_label}' already '{DRAFT_TABLE}' me maujood hai.")
                continue

            # Step 3: Dono tables me nahi mila - matlab genuinely naya data hai, DRAFT_TABLE me insert karo
            print(f"'{period_label}' dono tables me absent hai. '{DRAFT_TABLE}' me naya insert ho raha hai...")
            period_start, period_end = parse_fy_dates(period_label)

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
