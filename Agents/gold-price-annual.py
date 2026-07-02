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
# CONFIGURATION: Jab live karna ho, toh bas yahan table ka naam badal dein
# =====================================================================
DESTINATION_TABLE = "automation_test" 
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

# Automation detection bypass
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

chrome_options.add_argument("--window-size=1366,768")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.set_page_load_timeout(50) 
wait = WebDriverWait(driver, 35)

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
    # 1. Go to URL
    print("Page open ho raha hai...")
    try:
        driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")
    except Exception as e:
        print(f"Initial load handle/timeout alert: {e}")
        
    print("Settle hone ke liye explicitly wait kar rahe hain...")
    time.sleep(12) 
    driver.save_screenshot("step1_initial_page.png")
    print("Step 1 ka screenshot save ho gaya.")
    
    # Browser Alert Box Handler
    try:
        alert = driver.switch_to.alert
        print(f"Alert detect hua: {alert.text}. Dismissing alert...")
        alert.dismiss()
        time.sleep(3)
    except Exception:
        print("Koi standard browser alert window nahi mili, aage badh rahe hain.")

    # 2. Type "gold average" in search box
    print("Search box me text enter ho raha hai...")
    # Robust Backup: Agar placeholder direct render nahi hua toh input type search direct target hoga
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("gold average")
    
    time.sleep(3)  
    driver.save_screenshot("step2_search_text_entered.png")
    print("Step 2 ka screenshot save ho gaya.")
    
    # 3 & 4. Select dropdown option "With all of the words"
    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select = Select(dropdown_element)
    select.select_by_value("oneormorewords")
    time.sleep(3)  
    driver.save_screenshot("step3_dropdown_selected.png")
    print("Step 3 ka screenshot save ho gaya.")
    
    # 5. Click "Update Results" button
    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.search_button")))
    driver.execute_script("arguments[0].click();", update_btn)
    
    print("Results update hone ke liye full structural wait...")
    time.sleep(8)  
    driver.save_screenshot("step4_results_updated.png")
    print("Step 4 ka screenshot save ho gaya.")
    
    # Click on the first link
    print("First link par click ho raha hai...")
    first_link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Gold and Silver - Yearly Average Price')]")))
    
    main_window = driver.current_window_handle
    driver.execute_script("arguments[0].click();", first_link)
    
    print("Link click ho gaya. Tabs check karne ke liye safe hold...")
    time.sleep(12)
    driver.save_screenshot("step5_link_clicked.png")
    print("Step 5 ka screenshot save ho gaya.")
    
    # 6. Switch to naye tab aur wait
    print("Naye tab handles verify ho rahe hain...")
    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Naye tab par switch successfully ho gaye.")
                break
    else:
        print("ALERT: Background me dusra tab detect nahi hua. Current window par hi try karenge.")
            
    print("Loading spinner ke khatam hone ka explicit wait...")
    time.sleep(8)

    # Iframe Context Switch Logic
    print("Iframe dhoondh kar switch kiya ja raha hai...")
    try:
        iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
        driver.switch_to.frame(iframe_element)
        print("Successfully switched inside the data iframe.")
    except Exception as iframe_err:
        print(f"Iframe context direct target nahi hua, standard context par check rakhenge: {iframe_err}")

    # Robust Retry Loop for Table Loading & Screenshot Verification
    print("Table elements check karne ke liye custom verification loop shuru...")
    table_loaded = False
    for attempt in range(1, 7): 
        print(f"Attempt {attempt}: New HTML structure ke rows verify kiye ja rahe hain...")
        all_rows = driver.find_elements(By.XPATH, "//td[@bid='76' or @bid='72']/ancestor::tr")
        
        if len(all_rows) > 0:
            print(f"SUCCESS: Table load ho gayi, {len(all_rows)} elements target ho chuke hain.")
            table_loaded = True
            driver.save_screenshot("step6_data_tab_loaded.png")
            print("Step 6 data tab loaded screenshot capture ho gaya.")
            break
        else:
            print(f"Table abhi nahi mili. Capture kar rahe hain step6_attempt_{attempt}.png")
            driver.save_screenshot(f"step6_attempt_{attempt}.png")
            time.sleep(5)
            
    if not table_loaded:
        print("CRITICAL: Table load nahi ho saki. Forcing final screenshot.")
        driver.save_screenshot("step6_data_tab_loaded.png")
    
    # Dynamic Data Extraction: Aapke diye HTML match logic ke mutabik parsing
    print("Aapke HTML structure ke mutabik data extract ho raha hai...")
    all_rows = driver.find_elements(By.XPATH, "//tr[./td[@bid='76']]")
    
    period_label = None
    gold_mumbai_raw = None
    
    for row in all_rows:
        try:
            p_label = row.find_element(By.XPATH, "./td[@bid='76']//span").get_attribute("textContent").strip()
            g_raw = row.find_element(By.XPATH, "./td[@bid='72']//span").get_attribute("textContent").strip()
            
            if p_label and g_raw and g_raw != "":
                period_label = p_label
                gold_mumbai_raw = g_raw
                break
        except Exception:
            continue

    print(f"Extracted Data -> Year: {period_label}, Price: {gold_mumbai_raw}")
    
    if period_label and gold_mumbai_raw:
        value = float(gold_mumbai_raw.replace(',', '').strip())
        
        print(f"Database table '{DESTINATION_TABLE}' me existing record check ho raha hai...")
        response = supabase.table(DESTINATION_TABLE).select("*").eq("dataset_id", 1).eq("period_label", period_label).execute()
        
        if len(response.data) == 0:
            print(f"Naya data mila! Database table '{DESTINATION_TABLE}' me insert ho raha hai...")
            period_start, period_end = parse_fy_dates(period_label)
            
            data_to_insert = {
                "dataset_id": 1,
                "period_type": "FY",
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "value": value,
                "note": "NEW",
                "is_active": False,
                "created_by": "AUTOMATION"
            }
            
            insert_resp = supabase.table(DESTINATION_TABLE).insert(data_to_insert).execute()
            print("Data successfully insert ho gaya.")
        else:
            # Entry already mil gayi hai, ab value cross-check karenge
            existing_record = response.data[0]
            existing_id = existing_record.get("id") # Primary Key check karne ke liye
            existing_value = float(existing_record.get("value"))
            
            if existing_value != value:
                print(f"Gadbadi mili! Supabase value: {existing_value} vs Extracted value: {value}. Correction shuru...")
                
                correction_note = f"corrected datapoint from {existing_value} to {value}"
                
                # Agar table me id primary key hai toh use karenge, nahi toh dataset_id aur period_label par filter karenge
                query = supabase.table(DESTINATION_TABLE).update({"value": value, "note": correction_note})
                if existing_id:
                    update_resp = query.eq("id", existing_id).execute()
                else:
                    update_resp = query.eq("dataset_id", 1).eq("period_label", period_label).execute()
                    
                print(f"SUCCESS: Database correction done -> {correction_note}")
            else:
                print(f"Year {period_label} ka data perfectly match ho raha hai ({value}). Database up-to-date hai.")
    else:
        print("Table me koi bhi valid non-empty row ya matching bid attribute nahi mila.")

finally:
    driver.quit()
    print("Browser closed.")
