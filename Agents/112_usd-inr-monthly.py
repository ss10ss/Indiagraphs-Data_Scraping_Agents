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
import os

# =====================================================================
# CONFIGURATION: Target Tables & Dataset Specs
# =====================================================================
CHECK_TABLE = "automation_test"   
DRAFT_TABLE = "automation_test"   
DATASET_ID = 112
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

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.set_page_load_timeout(90) 
wait = WebDriverWait(driver, 60)

def parse_monthly_dates(period_label):
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
    time.sleep(2)  
    driver.save_screenshot("step2_search_text_entered.png")
    
    # GOLD SCRIPT PATTERN - Dropdown Implementation
    print("Dropdown select ho raha hai: With all of the words...")
    dropdown_element = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "select.dropdown_search")))
    select_filter = Select(dropdown_element)
    select_filter.select_by_value("allwords")
    time.sleep(2)
    driver.save_screenshot("step3_dropdown_selected.png")
    
    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    try:
        update_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", update_btn)
    
    print("Link load hone ka natural flow wait...")
    driver.save_screenshot("step4_results_updated.png")
    
    print("USD to INR Monthly Average Rate Link par click ho raha hai...")
    monthly_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Exchange Rate of the Indian Rupee vis-a-vis the SDR, US Dollar, Pound Sterling (Monthly Average and End-Month Rates)')]")))
    
    main_window = driver.current_window_handle
    try:
        monthly_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", monthly_link)
    
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
    try:
        all_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//*[@bid='790' or @bid='791']")))
        print(f"SUCCESS: Table load ho gayi, elements mil chuke hain.")
        table_loaded = True
        driver.save_screenshot("step6_data_tab_loaded.png")
    except Exception:
        table_loaded = False
        
    if not table_loaded:
        driver.save_screenshot("step6_data_tab_loaded.png")
        raise Exception("CRITICAL: Table load nahi ho saki.")
    
    print("Monthly Data processing shuru...")
    table_rows = driver.find_elements(By.XPATH, "//tr[td[@bid='790']]")
    
    scraped_data_list = []
    
    for row in table_rows:
        try:
            month_elements = row.find_elements(By.XPATH, "./td[@bid='790' and @c='1']//span")
            val_elements = row.find_elements(By.XPATH, "./td[@bid='791' and @c='4']//span")
            
            if month_elements and val_elements:
                raw_month = month_elements[0].get_attribute("textContent").strip()
                raw_val = val_elements[0].get_attribute("textContent").strip()
                
                if raw_month and raw_val:
                    full_period_label = raw_month.replace('-', ' ').strip().title()
                    val = float(raw_val.replace(',', '').strip())
                    scraped_data_list.append({"period_label": full_period_label, "value": val})
        except Exception:
            continue

    scraped_data_list = scraped_data_list[:5]
    scraped_data_list.reverse()

    valid_rows_count = 0
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]
            
            valid_rows_count += 1
            print(f"\nProcessing Monthly Row {valid_rows_count} -> Month: {period_label}, Value: {value}")
            
            response = supabase.table(CHECK_TABLE).select("*").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            
            if len(response.data) == 0:
                print(f"Data missing in '{CHECK_TABLE}'! Table '{DRAFT_TABLE}' me draft insert ho raha hai...")
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
                    "source_note": "via AUTOMATION"
                }
                
                insert_resp = supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
                print(f"SUCCESS: Month {period_label} ka naya data '{DRAFT_TABLE}' me chala gaya.")
            else:
                existing_record = response.data[0]
                existing_id = existing_record.get("id")
                existing_value = float(existing_record.get("value"))
                
                if existing_value != value:
                    print(f"Gadbadi mili! Supabase ({CHECK_TABLE}): {existing_value} vs Extracted: {value}. Correction shuru...")
                    correction_note = f"Updated datapoint from {existing_value} to {value}"
                    
                    query = supabase.table(CHECK_TABLE).update({"value": value, "note": correction_note})
                    if existing_id:
                        update_resp = query.eq("id", existing_id).execute()
                    else:
                        update_resp = query.eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
                        
                    print(f"SUCCESS: Table '{CHECK_TABLE}' correction done -> {correction_note}")
                else:
                    print(f"Month {period_label} ka data '{CHECK_TABLE}' me perfectly match ho raha hai.")
                    
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
