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

# Supabase Credentials (GitHub Actions secrets se aayenge)
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

# Automation detection bypass (Isse RBI block nahi karega)
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

chrome_options.add_argument("--window-size=1366,768")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.set_page_load_timeout(60) 
wait = WebDriverWait(driver, 25)

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
        print(f"Initial load timeout alert (bypassing to continue execution): {e}")
        
    time.sleep(6) 
    driver.save_screenshot("step1_initial_page.png")
    
    # 2. Type "gold average" in search box
    print("Search box me text enter ho raha hai...")
    search_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Search']")))
    search_box.clear()
    search_box.send_keys("gold average")
    driver.save_screenshot("step2_search_text_entered.png")
    
    # 3 & 4. Select dropdown option "With all of the words"
    print("Dropdown select ho raha hai...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select = Select(dropdown_element)
    select.select_by_value("oneormorewords")
    driver.save_screenshot("step3_dropdown_selected.png")
    
    # 5. Click "Update Results" button
    print("Update Results button par click ho raha hai...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    update_btn.click()
    time.sleep(4)
    driver.save_screenshot("step4_results_updated.png")
    
    # Click on the first link
    print("First link par click ho raha hai...")
    first_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Gold and Silver - Yearly Average Price')]")))
    
    # Store old window handle
    main_window = driver.current_window_handle
    first_link.click()
    print("Link click ho gaya. Tabs check karne ke liye safe hold...")
    time.sleep(10)
    driver.save_screenshot("step5_link_clicked.png")
    
    # 6. Switch to naye tab aur wait
    print("Naye tab handles verify ho rahe hain...")
    
    # Lambda wait hatakar simple conditional checking taaki timeout exception se script crash na ho
    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Naye tab par switch successfully ho gaye.")
                break
    else:
        print("ALERT: Background me dusra tab detect nahi hua. Current window par hi try karenge.")
            
    print("Naye tab ko stable karne ke liye 15 seconds ka explicit hold...")
    time.sleep(15) 
    driver.save_screenshot("step6_data_tab_loaded.png")
    
    # Dynamic Data Extraction: Pehli non-empty row dhoondhna
    print("Valid data row extract ho rahi hai...")
    first_row_check = wait.until(EC.presence_of_element_located((By.XPATH, "//table[@bid='80']/tbody/tr")))
    all_rows = driver.find_elements(By.XPATH, "//table[@bid='80']/tbody/tr")
    
    period_label = None
    gold_mumbai_raw = None
    
    # Top rows par loop chala kar check karenge jisme data blank na ho
    for row in all_rows:
        try:
            p_label = row.find_element(By.XPATH, "./td[@c='0']//span").text.strip()
            g_raw = row.find_element(By.XPATH, "./td[@c='1']//span").text.strip()
            
            # Agar dono values mil jayein aur blank na hon, toh loop rok dein
            if p_label and g_raw and g_raw != "":
                period_label = p_label
                gold_mumbai_raw = g_raw
                break
        except Exception:
            continue

    print(f"Extracted Data -> Year: {period_label}, Price: {gold_mumbai_raw}")
    
    if period_label and gold_mumbai_raw:
        # Clean numeric value (Commas hatana)
        value = float(gold_mumbai_raw.replace(',', ''))
        
        # Supabase me check karein ki ye period_label pehle se hai ya nahi
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
            print(f"Year {period_label} ka data database me pehle se maujood hai. No changes made.")
    else:
        print("Table me koi bhi valid non-empty row nahi mili.")

finally:
    driver.quit()
    print("Browser closed.")
