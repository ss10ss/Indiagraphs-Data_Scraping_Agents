import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client

# =====================================================================
# Dataset Specs
# =====================================================================
DATASET_ID = '244'
SOURCE_NOTE = 'NSE Nifty 50 Closing Index Value'
CREATED_BY = 'c7dcaab6-1312-4d08-8b39-d327827d885f'
TARGET_URL = 'https://www.nseindia.com/'
MAX_RETRIES = 3
# =====================================================================

# --- Supabase Setup ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=options)


def parse_numeric(text: str) -> float:
    cleaned = text.replace(",", "").replace("\u00a0", "").strip()
    if cleaned == "":
        raise ValueError("Empty string encountered while parsing numeric value")
    return float(cleaned)


def check_existing(dataset_id: str, period_start: str) -> bool:
    result = (
        supabase.table("daily_data_points")
        .select("id")
        .eq("dataset_id", dataset_id)
        .eq("period_start", period_start)
        .execute()
    )
    return len(result.data) > 0


def insert_datapoint(dataset_id: str, period_label: str, period_start: str, value: float, source_note: str) -> None:
    supabase.table("daily_data_points").insert(
        {
            "dataset_id": dataset_id,
            "period_type": "DAY",
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_start,
            "value": value,
            "note": None,
            "source_note": source_note,
            "is_active": True,
            "created_by": CREATED_BY,
        }
    ).execute()


def scrape():
    driver = init_driver()
    wait = WebDriverWait(driver, 30)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"--- Navigation attempt {attempt}/{MAX_RETRIES} ---")

            print("Opening page...")
            driver.get(TARGET_URL)

            print("Waiting for page to settle...")
            time.sleep(5)

            print("Waiting for the Nifty 50 value to be visible...")
            value_element = wait.until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, "div.symbol_value span.value")
                )
            )

            raw_value_text = value_element.text.strip()
            print(f"Raw Nifty 50 value text: '{raw_value_text}'")

            value = parse_numeric(raw_value_text)
            print(f"Parsed Nifty 50 value: {value}")

            today = datetime.now()
            period_label = today.strftime("%d %b %Y")
            period_start = today.strftime("%Y-%m-%d")

            print(f"Period label: {period_label}")
            print(f"Period start: {period_start}")

            # --- Screenshot ---
            screenshot_path = f"screenshot_{period_start}.png"
            driver.save_screenshot(screenshot_path)
            print(f"Screenshot saved: {screenshot_path}")

            # --- Insert Logic ---
            print(f"Checking Nifty 50 (dataset_id={DATASET_ID}) for {period_start}...")
            if check_existing(DATASET_ID, period_start):
                print(
                    f"Nifty 50 data for {period_label} already exists in daily_data_points. Skipping insert."
                )
            else:
                insert_datapoint(
                    DATASET_ID, period_label, period_start, value, SOURCE_NOTE
                )
                print(
                    f"SUCCESS: Nifty 50 data for {period_label} inserted into daily_data_points."
                )

            print("Scraping and insertion complete.")
            break

        except Exception as e:
            print(f"Error during navigation attempt {attempt}: {e}")
            try:
                driver.save_screenshot(f"error_screenshot_attempt_{attempt}.png")
                print(f"Error screenshot captured: error_screenshot_attempt_{attempt}.png")
            except Exception as ss_e:
                print(f"Failed to capture error screenshot: {ss_e}")

            if attempt == MAX_RETRIES:
                print("CRITICAL: All retry attempts exhausted.")
                raise
            print("Retrying after a short delay...")
            time.sleep(5)

    driver.quit()
    print("Browser closed.")


if __name__ == "__main__":
    scrape()
