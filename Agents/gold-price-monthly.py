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
# CONFIGURATION: Monthly Scraper Target Table
# =====================================================================
DESTINATION_TABLE = "automation_test" 
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
driver.set_page_load_timeout(50) 
wait = WebDriverWait(driver, 35)

def parse_monthly_dates(period_label):
    """
    Format handle karta hai: 'Mar 2026' ya 'MAR 2025' -> (2026-03-01, 2026-03-31)
    """
    try:
        parts = period_label.strip().split()
        if len(parts) != 2:
            return None, None
        
        month_str, year_str = parts[0].title(), parts[1]
        
        # Month name se month number nikalna (e.g., 'Mar' -> 3)
        month_modules = {v: k for k, v in enumerate(calendar.month_abbr)}
        month_num = month_modules.get(month_str[:3])
        
        if not month_num:
            # Full month name mapping fallback
            month_modules_full = {v: k for k, v in enumerate(calendar.month_name)}
            month_num = month_modules_full.get(month_str)
            
        if not month_num:
            return None, None
            
        year = int(year_str)
        
        # Month ki starting aur ending date nikalna
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
            time.sleep(5)
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.set_page_load_timeout(50)
            wait = WebDriverWait(driver, 35)
        
    print("Settle hone ke liye explicitly wait kar rahe hain...")
    time.sleep(12) 
    
    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(3)
    except Exception:
        pass

    print("Search box me 'gold average' enter ho raha hai...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("gold average")
    time.sleep(3)  
    
    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select = Select(dropdown_element)
    select.select_by_value("oneormorewords")
    time.sleep(3)  
    
    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.search_button")))
    driver.execute_script("arguments[0].click();", update_btn)
    time.sleep(8)  
    
    # FIX: Specially Monthly matching target link (3rd Link) par click karne ke liye XPATH
    print("Monthly Link par click ho raha hai...")
    monthly_link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Monthly Average Price of Gold and Silver')]")))
    
    main_window = driver.current_window_handle
    driver.execute_script("arguments[0].click();", monthly_link)
    time.sleep(12)
    
    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Naye tab par switch successfully ho gaye.")
                break
            
    time.sleep(8)

    print("Iframe dhoondh kar switch kiya ja raha hai...")
    try:
        iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
        driver.switch_to.frame(iframe_element)
        print("Inside data iframe switched.")
    except Exception as iframe_err:
        print(f"Standard context fallback: {iframe_err}")

    print("Table cells validation loop shuru...")
    table_loaded = False
    for attempt in range(1, 7): 
        all_rows = driver.find_elements(By.XPATH, "//td[@bid='76' or @bid='72']/ancestor::tr")
        if len(all_rows) > 0:
            print(f"SUCCESS: Table load ho gayi, {len(all_rows)} elements target ho chuke hain.")
            table_loaded = True
            break
        else:
            time.sleep(5)
            
    if not table_loaded:
        raise Exception("CRITICAL: Table load nahi ho saki.")
    
    print("Monthly Data extract ho raha hai...")
    all_rows = driver.find_elements(By.XPATH, "//tr[./td[@bid='76']]")
    
    # Top 5 entries ka data collect karenge (Latest months)
    scraped_data_list = []
    for row in all_rows[:5]:
        try:
            p_label = row.find_element(By.XPATH, "./td[@bid='76']//span").get_attribute("textContent").strip()
            g_raw = row.find_element(By.XPATH, "./td[@bid='72']//span").get_attribute("textContent").strip()
            
            # Sub-headers (jaise Year headers '2026-27') ko filter karne ke liye condition
            if p_label and "-" not in p_label and g_raw and g_raw != "":
                val = float(g_raw.replace(',', '').strip())
                scraped_data_list.append({"period_label": p_label, "value": val})
        except Exception as e:
            continue

    # Chronological indexing set karne ke liye list ko reverse (purane se naya) karenge
    scraped_data_list.reverse()

    valid_rows_count = 0
    
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]  # Example: "Mar 2026"
            value = item["value"]
            
            valid_rows_count += 1
            print(f"\nProcessing Monthly Row {valid_rows_count} -> Month: {period_label}, Price: {value}")
            
            # Database check with dataset_id = 110
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
                    "is_active": True,  # Monthly screenshot ke hisab se TRUE
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
            print(f"Row database operation error: {row_err}")
            continue

    print(f"\nScraping complete! Total {valid_rows_count} monthly rows process ki gayi hain.")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
