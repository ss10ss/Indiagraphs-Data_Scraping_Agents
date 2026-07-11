import time
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
driver.set_page_load_timeout(60) 
wait = WebDriverWait(driver, 45)

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

try:
    print("Page open ho raha hai...")
    for attempt in range(1, 4):
        try:
            print(f"URL load attempt {attempt}/3...")
            driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")
            break
        except Exception as e:
            print(f"Attempt {attempt} me initial load timeout ya error aaya: {e}")
            if attempt == 3:
                raise e
            print("Driver ko restart karke fresh session ke sath retry kar rahe hain...")
            try:
                driver.quit()
            except Exception:
                pass
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.set_page_load_timeout(60)
            wait = WebDriverWait(driver, 45)
        
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
    
    print("Aapke HTML structure ke mutabik data extract ho raha hai...")
    all_rows = driver.find_elements(By.XPATH, "//tr[./td[@bid='76']]")
    
    scraped_data_list = []
    for row in all_rows[:3]:
        try:
            p_label = row.find_element(By.XPATH, "./td[@bid='76']//span").get_attribute("textContent").replace("–", "-").strip()
            g_raw = row.find_element(By.XPATH, "./td[@bid='72']//span").get_attribute("textContent").strip()
            
            if p_label and g_raw and g_raw != "":
                # FIXED: int hata kar pure float rakha decimal points ke liye
                val = float(g_raw.replace(',', '').strip())
                scraped_data_list.append({"period_label": p_label, "value": val})
        except Exception as e:
            print(f"Raw parse error: {e}")
            continue

    scraped_data_list.reverse()

    valid_rows_count = 0
    for item in scraped_data_list:
        try:
            period_label = item["period_label"]
            value = item["value"]
            
            valid_rows_count += 1
            print(f"\nProcessing Yearly Row {valid_rows_count} -> Year: {period_label}, Price: {value}")
            
            response = supabase.table(CHECK_TABLE).select("*").eq("dataset_id", DATASET_ID).eq("period_label", period_label).execute()
            
            matched_record = None
            if len(response.data) == 0:
                print(f"Direct match nahi mila '{period_label}' ka. Safe fetch try kar rahe hain...")
                all_db_records = supabase.table(CHECK_TABLE).select("*").eq("dataset_id", DATASET_ID).execute()
                for rec in all_db_records.data:
                    db_label = rec.get("period_label", "").replace("–", "-").strip()
                    if db_label == period_label:
                        matched_record = rec
                        break
            else:
                matched_record = response.data[0]

            if not matched_record:
                print(f"Data missing in '{CHECK_TABLE}'! Table '{DRAFT_TABLE}' me draft insert ho raha hai...")
                period_start, period_end = parse_fy_dates(period_label)
                
                data_to_insert = {
                    "dataset_id": DATASET_ID,
                    "period_type": "FY",
                    "period_label": period_label,
                    "period_start": period_start,
                    "period_end": period_end,
                    "value": value,
                    "note": "NEW",
                    "is_active": False,
                    "source_note": "via AUTOMATION"
                }
                
                insert_resp = supabase.table(DRAFT_TABLE).insert(data_to_insert).execute()
                print(f"SUCCESS: Year {period_label} ka naya data '{DRAFT_TABLE}' me chala gaya.")
            else:
                existing_id = matched_record.get("id")
                existing_value_raw = matched_record.get("value")
                
                # FIXED: Database ki numerical value ko bhi pure float me cast kiya (no integer truncation)
                existing_value = float(str(existing_value_raw).replace(',', '').strip()) if existing_value_raw else 0.0
                
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
                    print(f"Year {period_label} ka data '{CHECK_TABLE}' me perfectly match ho raha hai.")
                    
        except Exception as row_err:
            print(f"Row operation error: {row_err}")
            continue

    print(f"\nScraping complete! Total {valid_rows_count} yearly rows process ki gayi hain.")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    print("Browser closed.")
