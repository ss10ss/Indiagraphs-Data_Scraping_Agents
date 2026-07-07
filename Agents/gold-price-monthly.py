import time
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

# =====================================================================
# CONFIGURATION: Target Table & Dataset Specs
# =====================================================================
DESTINATION_TABLE = "data_points" 
DATASET_ID = 110
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

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
# Page load timeout badhaya 50 -> 90, kyunki renderer timeout 48s pe hi hit ho raha tha CI me
driver.set_page_load_timeout(90)
# Explicit wait timeout badhaya 35 -> 60, DBIE ka variable load time absorb karne ke liye
wait = WebDriverWait(driver, 60)


def parse_monthly_dates(period_label):
    """
    Format handle karta hai: 'Mar 2026' -> (2026-03-01, 2026-03-31)
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
        print(f"Monthly Date parse karne me error: {e}")
        return None, None


def wait_for_new_tab(driver, main_window, timeout=30, poll=0.5):
    """Fixed sleep ki jagah — jab tak naya tab actually na khule, poll karte raho."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        handles = driver.window_handles
        if len(handles) > 1:
            return handles
        time.sleep(poll)
    return driver.window_handles


def wait_for_table_elements(driver, xpath, timeout=60, poll=2):
    """Fixed 6-attempt loop ki jagah — actual timeout tak poll karo, sirf attempt count tak nahi."""
    end_time = time.time() + timeout
    attempt = 0
    while time.time() < end_time:
        attempt += 1
        elements = driver.find_elements(By.XPATH, xpath)
        if len(elements) > 0:
            return elements, attempt
        driver.save_screenshot(f"step6_attempt_{attempt}.png")
        time.sleep(poll)
    return [], attempt


try:
    print("Page open ho raha hai...")
    for attempt in range(1, 4):
        try:
            print(f"URL load attempt {attempt}/3...")
            driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")
            break
        except Exception as e:
            print(f"Attempt {attempt} me error aaya: {e}")
            if attempt == 3:
                raise e
            try:
                driver.quit()
            except Exception:
                pass
            time.sleep(5)
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.set_page_load_timeout(90)
            wait = WebDriverWait(driver, 60)
        
    driver.save_screenshot("step1_initial_page.png")
    
    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(2)
    except Exception:
        pass

    # Fixed time.sleep(12) hataya — search_box ke liye wait.until already
    # DBIE ke actual render hone tak (10s ho ya 25s ho) poll karta rahega, hardcoded 12s nahi.
    print("Search box me 'gold average' enter ho raha hai...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("gold average")
    driver.save_screenshot("step2_search_text_entered.png")
    
    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select = Select(dropdown_element)
    select.select_by_text("With all of the words")
    driver.save_screenshot("step3_dropdown_selected.png")
    
    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.search_button")))
    driver.execute_script("arguments[0].click();", update_btn)
    # Fixed sleep(8) hataya — seedha next element (monthly_link) ka wait.until
    # actual load hone tak poll karega
    driver.save_screenshot("step4_results_updated.png")
    
    print("Monthly Link par click ho raha hai...")
    monthly_link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Monthly Average Price of Gold and Silver')]")))
    
    main_window = driver.current_window_handle
    driver.execute_script("arguments[0].click();", monthly_link)
    
    print("Naya tab open hone ka explicit poll wait...")
    current_handles = wait_for_new_tab(driver, main_window, timeout=30)
    driver.save_screenshot("step5_link_clicked.png")
    
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Naye tab par switch successfully ho gaye.")
                break

    print("Iframe dhoondh kar switch kiya ja raha hai...")
    try:
        # Iframe wait bhi 60s tak poll karega (wait object ka timeout use ho raha hai)
        iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
        driver.switch_to.frame(iframe_element)
        print("Successfully switched inside data iframe.")
    except Exception as iframe_err:
        print(f"Iframe context fallback: {iframe_err}")

    print("Table elements validation loop shuru...")
    all_elements, attempts_taken = wait_for_table_elements(
        driver,
        "//*[@bid='4827' or @bid='4826' or @bid='4944']",
        timeout=60,
        poll=3
    )
    table_loaded = len(all_elements) > 0
    driver.save_screenshot("step6_data_tab_loaded.png")

    if not table_loaded:
        raise Exception(f"CRITICAL: Table load nahi ho saki ({attempts_taken} attempts, 60s timeout ke baad bhi).")
    print(f"SUCCESS: Table load ho gayi ({attempts_taken} attempts me).")
    
    print("Monthly Data processing shuru...")
    table_rows = driver.find_elements(By.XPATH, "//tr[th[@bid='4944'] or td[@bid='4827']]")
    
    scraped_data_list = []
    current_fy = None
    
    for row in table_rows:
        try:
            year_headers = row.find_elements(By.XPATH, "./th[@bid='4944']//span")
            if year_headers:
                current_fy = year_headers[0].get_attribute("textContent").strip()
                continue
                
            month_elements = row.find_elements(By.XPATH, "./td[@bid='4827' and @c='0']//span")
            val_elements = row.find_elements(By.XPATH, "./td[@bid='4826' and @c='1']//span")
            
            if month_elements and val_elements and current_fy:
                raw_month = month_elements[0].get_attribute("textContent").strip().title()
                raw_val = val_elements[0].get_attribute("textContent").strip()
                
                if raw_month and raw_val:
                    fy_start = int(current_fy.split('-')[0].strip())
                    fy_end = int(current_fy.split('-')[1].strip())
                    if len(str(fy_end)) == 2:
                        fy_end = int(str(fy_start)[:2] + str(fy_end))
                        
                    target_year = fy_end if raw_month.upper() in ["JAN", "FEB", "MAR"] else fy_start
                    full_period_label = f"{raw_month} {target_year}"
                    
                    val = int(round(float(raw_val.replace(',', '').strip())))
                    scraped_data_list.append({"period_label": full_period_label, "value": val})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:5]
    scraped_data_list.reverse()

    # Naya safety check: agar parsing ke baad bhi zero rows hain, silently pass hone ke bajaye
    # explicitly fail karo taaki GitHub Actions run red ho aur pata chale
    if len(scraped_data_list) == 0:
        raise Exception("CRITICAL: Table load toh hui lekin zero rows parse hue. Selector/bid mismatch ho sakta hai.")

    valid_rows_count = 0
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]
            
            valid_rows_count += 1
            print(f"\nProcessing Monthly Row {valid_rows_count} -> Month: {period_label}, Price: {value}")
            
            response = supabase.table(DESTINATION_TABLE).select("*").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            
            if len(response.data) == 0:
                print(f"Data missing! Table '{DESTINATION_TABLE}' me insert ho raha hai...")
                period_start, period_end = parse_monthly_dates(period_label)
                
                data_to_insert = {
                    "dataset_id": DATASET_ID,
                    "period_type": "MONTH",
                    "period_label": period_label,
                    "period_start": period_start,
                    "period_end": period_end,
                    "value": value,
                    "note": "NEW",
                    "is_active": False,  
                    "created_by": "AUTOMATION"
                }
                
                insert_resp = supabase.table(DESTINATION_TABLE).insert(data_to_insert).execute()
                print(f"SUCCESS: Month {period_label} ka missing data insert ho gaya.")
            else:
                existing_record = response.data[0]
                existing_id = existing_record.get("id")
                existing_value = float(existing_record.get("value"))
                
                if existing_value != value:
                    print(f"Gadbadi mili! Supabase: {existing_value} vs Extracted: {value}. Correction shuru...")
                    correction_note = f"Updated datapoint from {existing_value} to {value}"
                    
                    query = supabase.table(DESTINATION_TABLE).update({"value": value, "note": correction_note})
                    if existing_id:
                        update_resp = query.eq("id", existing_id).execute()
                    else:
                        update_resp = query.eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
                        
                    print(f"SUCCESS: Database correction done -> {correction_note}")
                else:
                    print(f"Month {period_label} ka data perfectly match ho raha hai.")
                    
        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            continue

    print(f"\nScraping complete! Total {valid_rows_count} monthly rows process ki gayi hain.")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
