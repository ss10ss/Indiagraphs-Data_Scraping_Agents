import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client

# --- Supabase Setup ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

GOLD_DATASET_ID = '233'
SILVER_DATASET_ID = '234'
CREATED_BY = 'c7dcaab6-1312-4d08-8b39-d327827d885f'
TARGET_URL = 'https://ibjarates.com/'
MAX_RETRIES = 3


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def format_period_label(date_str: str) -> str:
    dt = datetime.strptime(date_str.strip(), "%d/%m/%Y")
    return dt.strftime("%d %b %Y")


def format_period_start(date_str: str) -> str:
    dt = datetime.strptime(date_str.strip(), "%d/%m/%Y")
    return dt.strftime("%Y-%m-%d")


def parse_numeric(text: str) -> int:
    cleaned = text.replace(",", "").replace("\u00a0", "").strip()
    if cleaned == "":
        raise ValueError("Empty string encountered while parsing numeric value")
    return int(cleaned)


def check_existing(dataset_id: str, period_start: str) -> bool:
    result = (
        supabase.table("daily_data_points")
        .select("id")
        .eq("dataset_id", dataset_id)
        .eq("period_start", period_start)
        .execute()
    )
    return len(result.data) > 0


def insert_datapoint(dataset_id: str, period_label: str, period_start: str, value: int) -> None:
    supabase.table("daily_data_points").insert(
        {
            "dataset_id": dataset_id,
            "period_type": "DAY",
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_start,
            "value": value,
            "note": None,
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
            time.sleep(4)

            # --- Close Popup ---
            print("Attempting to close popup...")
            try:
                close_btn = wait.until(
                    EC.element_to_be_clickable((By.ID, "closePopup"))
                )
                close_btn.click()
                print("Popup closed successfully.")
                time.sleep(2)
            except Exception:
                print("No popup detected or already dismissed, continuing...")

            # --- Scroll PM tab into view and click via JavaScript ---
            print("Locating PM tab and clicking via JavaScript...")
            pm_tab = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "table.propage-tab.apm a[href='#tab-pm']")
                )
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", pm_tab)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", pm_tab)
            print("PM tab clicked via JavaScript.")
            time.sleep(2)

            # --- Wait for PM tab content to be visible ---
            print("Waiting for PM tab content to become visible...")
            wait.until(
                EC.visibility_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "table.propage-tab.apm div#tab-pm table.table-striped tbody tr",
                    )
                )
            )

            rows = driver.find_elements(
                By.CSS_SELECTOR,
                "table.propage-tab.apm div#tab-pm table.table-striped tbody tr",
            )

            if not rows:
                raise RuntimeError("No rows found in PM tab under Previous Dates Rate table")

            print(f"Total rows found in PM tab (Previous Dates): {len(rows)}")
            first_row = rows[0]

            date_cell = first_row.find_element(By.CSS_SELECTOR, "td[data-label='PM']")
            gold_cell = first_row.find_element(By.CSS_SELECTOR, "td[data-label='Gold 999']")
            silver_cell = first_row.find_element(By.CSS_SELECTOR, "td[data-label='Silver 999']")

            raw_date = date_cell.text.strip()
            gold_raw_text = gold_cell.text
            silver_raw_text = silver_cell.text

            print(f"Raw date cell text (topmost row): '{raw_date}'")
            print(f"Raw Gold 999 cell text (topmost row): '{gold_raw_text}'")
            print(f"Raw Silver 999 cell text (topmost row): '{silver_raw_text}'")

            gold_999_value = parse_numeric(gold_raw_text)
            silver_999_value = parse_numeric(silver_raw_text)

            print(f"Parsed Gold 999 value: {gold_999_value}")
            print(f"Parsed Silver 999 value: {silver_999_value}")

            period_label = format_period_label(raw_date)
            period_start = format_period_start(raw_date)

            print(f"Period label: {period_label}")
            print(f"Period start: {period_start}")

            # --- Screenshot ---
            screenshot_path = f"screenshot_{period_start}.png"
            driver.save_screenshot(screenshot_path)
            print(f"Screenshot saved: {screenshot_path}")

            # --- Gold 999 Insert Logic ---
            print(f"Checking Gold 999 (dataset_id={GOLD_DATASET_ID}) for {period_start}...")
            if check_existing(GOLD_DATASET_ID, period_start):
                print(
                    f"Gold 999 data for {period_label} already exists in daily_data_points. Skipping insert."
                )
            else:
                insert_datapoint(
                    GOLD_DATASET_ID, period_label, period_start, gold_999_value
                )
                print(
                    f"SUCCESS: Gold 999 data for {period_label} inserted into daily_data_points."
                )

            # --- Silver 999 Insert Logic ---
            print(f"Checking Silver 999 (dataset_id={SILVER_DATASET_ID}) for {period_start}...")
            if check_existing(SILVER_DATASET_ID, period_start):
                print(
                    f"Silver 999 data for {period_label} already exists in daily_data_points. Skipping insert."
                )
            else:
                insert_datapoint(
                    SILVER_DATASET_ID, period_label, period_start, silver_999_value
                )
                print(
                    f"SUCCESS: Silver 999 data for {period_label} inserted into daily_data_points."
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
