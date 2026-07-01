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
# RBI ki blocking bypass karne ke liye real browser ka User-Agent header
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
# Script hanging se bachne ke liye page load timeout limit
driver.set_page_load_timeout(60) 
wait = WebDriverWait(driver, 20)

def parse_fy_dates(period_label):
    # Format "2025-26" -> Start: 2025-04-01, End: 2026-03-31
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
        
    time.sleep(5) 
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
    time.sleep(3)
    driver.save_screenshot("step4_results_updated.png")
    
    # Click on the first link
    print("First link par click ho raha hai...")
    first_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Gold and Silver - Yearly Average Price')]")))
    first_link.click()
    time.sleep(2)
    driver.save_screenshot("step5_link_clicked.png")
    
    # 6. Switch to naye tab aur wait
    print("Naye tab par switch ho rahe hain...")
    wait.until(lambda d: len(d.window_handles) > 1)
    driver.switch_to.window(driver.window_handles[1])
    
    print("Naye tab ke completely load hone aur table ke dikhne ka wait...")
    # Yeh tab tak wait karega jab tak table ka main element DOM me load hokar visibility nahi le leta (Max 30 seconds)
    table_wait = WebDriverWait(driver, 30)
    table_wait.until(EC.visibility_of_element_located((By.XPATH, "//table[@bid='80']")))
    
    # Ek safe screenshot capture karne ke liye 2 second ka pause jab table mil jaye
    time.sleep(2)
    driver.save_screenshot("step6_data_tab_loaded.png")
    
    # Latest Data Extraction (Pehli Row)
    print("Latest data extract ho raha hai...")
    first_row = wait.until(EC.presence_of_element_located((By.XPATH, "//table[@bid='80']/tbody/tr[@cid='1']")))
    
    # Year (Column 0)
    period_label = first_row.find_element(By.XPATH, "./td[@c='0']//span").text.strip()
    # Mumbai Gold Price (Column 1)
    gold_mumbai_raw = first_row.find_element(By.XPATH, "./td[@c='1']//span").text.strip()
    
    print(f"Extracted Data -> Year: {period_label}, Price: {gold_mumbai_raw}")
    
    if period_label and gold_mumbai_raw and gold_mumbai_raw != "":
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
        print("Latest row me valid data nahi mila.")

finally:
    driver.quit()
    print("Browser closed.")
