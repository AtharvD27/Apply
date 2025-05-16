import os
import time
import yaml
import logging
from datetime import datetime
import pandas as pd
import tempfile
from selenium import webdriver
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from dotenv import load_dotenv

# ====== CONFIG ======
def load_config(path="config/apply_job_config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config()
DELAY = config["delay"]
CSV_FILE = config["main_csv_file"]
EMAIL = os.getenv("SCRAPER_EMAIL") or config["email"]
PASSWORD = os.getenv("SCRAPER_PASSWORD") or config["password"]
DRIVER_PATH = config.get("driver_path", "/usr/local/bin/chromedriver")
LOG_DIR = Path(config.get("log_dir", "output/logs"))

# ====== Logging ======
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOG_DIR / f"apply_job_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    filename=str(log_filename),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()

load_dotenv()

import tempfile

def get_driver():
    chrome_options = Options()

    # ✅ Use safest headless mode
    chrome_options.add_argument("--headless=new")  # try "--headless=chrome" if this fails
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # ✅ Force Chrome version 136
    chrome_options.binary_location = "/opt/chrome/chrome"

    # ✅ Create an isolated unique user data dir (in working dir)
    user_data_dir = tempfile.mkdtemp(prefix="chrome-profile-", dir="/tmp")
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    driver_path = config.get("driver_path", "/usr/local/bin/chromedriver")
    service = Service(driver_path)

    # ✅ Start driver
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.implicitly_wait(3)

    return driver

def login_to_dice(driver):
    logger.info("Logging into Dice...")
    print("Logging into Dice...")
    driver.get("https://www.dice.com/dashboard/login")
    WebDriverWait(driver, DELAY).until(
        EC.presence_of_element_located((By.NAME, "email"))
    ).send_keys(EMAIL)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    WebDriverWait(driver, DELAY).until(
        EC.presence_of_element_located((By.NAME, "password"))
    ).send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    WebDriverWait(driver, DELAY).until(EC.url_contains("dashboard"))
    logger.info("Login successful.")
    print("Login successful.")

def easy_apply(driver, job_link, job_title):
    try:
        driver.get(job_link)
        time.sleep(DELAY)

        # Save job
        try:
            save_host = driver.find_element(By.CSS_SELECTOR, "dhi-job-search-save-job")
            outer_shadow = driver.execute_script("return arguments[0].shadowRoot", save_host)
            seds_button = outer_shadow.find_element(By.CSS_SELECTOR, "seds-button")
            inner_shadow = driver.execute_script("return arguments[0].shadowRoot", seds_button)
            button = inner_shadow.find_element(By.CSS_SELECTOR, "button")
            save_text = button.text.strip().lower()

            if "saved" in save_text:
                logger.info(f"SKIPPED Save (already saved): {job_title}")
                print(f"SKIPPED Save (already saved): {job_title}")
            else:
                seds_button.click()
                time.sleep(DELAY-2)
                logger.info(f"SAVED: {job_title}")
                print(f"SAVED: {job_title}")
        except Exception as e:
            logger.warning(f"Save button failed: {job_title} — {e}")
            print(f"Save button failed: {job_title}")

        # Check if already applied
        try:
            apply_component = driver.find_element(By.TAG_NAME, "apply-button-wc")
            shadow_root = driver.execute_script("return arguments[0].shadowRoot", apply_component)
            submitted_tag = shadow_root.find_elements(By.CSS_SELECTOR, ".application-submitted")
            if submitted_tag:
                logger.info(f"SKIPPED (already applied): {job_title}")
                print(f"SKIPPED (already applied): {job_title}")
                return "Applied"
        except Exception as e:
            logger.warning(f"Could not check status for {job_title} — {e}")
            print(f"Could not check status for {job_title}")

        # Easy Apply steps
        apply_button = driver.find_element(By.TAG_NAME, "apply-button-wc")
        apply_button.click()
        time.sleep(DELAY)

        next_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-next')]")
        next_btn.click()
        time.sleep(DELAY-2)

        final_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-next')]")
        final_btn.click()
        time.sleep(DELAY-2)

        logger.info(f"APPLIED: {job_title}")
        print(f"APPLIED: {job_title}")
        return "Applied"

    except (NoSuchElementException, ElementClickInterceptedException) as e:
        logger.error(f"FAILED to apply for {job_title} - {job_link}: {e}")
        print(f"FAILED to apply for {job_title} - {job_link}")
        return "Failed"

def main():
    driver = get_driver()
    login_to_dice(driver)

    df = pd.read_csv(CSV_FILE)
    df["date_posted"] = pd.to_datetime(df["date_posted"], errors="coerce")  # for sorting

    # 1. Filter only Easy Apply jobs
    easy_apply_df = df[df["apply_text"].str.strip().str.lower() == "easy apply"].copy()
    
    # 2. Further filter to only Pending status
    pending_df = easy_apply_df[easy_apply_df["status"].str.lower() != "applied"].copy()
    total_pending = len(pending_df)
    applied = 0

    for idx, row in pending_df.iterrows():
        result = easy_apply(driver, row["link"], row["title"])
        easy_apply_df.at[row.name, "status"] = result
        if result == "Applied":
            applied += 1

    # 3. Merge updated Easy Apply section back into full df
    df_remaining = df.drop(easy_apply_df.index)
    df_combined = pd.concat([df_remaining, easy_apply_df], ignore_index=True)

    # 4. Sort
    df_combined = df_combined.sort_values(
        by=["status", "date_posted", "apply_text"],
        ascending=[True, False, True]
    ).reset_index(drop=True)

    # 5. Save
    df_combined.to_csv(CSV_FILE, index=False)
    driver.quit()

    logger.info(f"[DONE] Newly applied: {applied} out of {total_pending} Easy Apply jobs (Total in CSV: {len(df)})")
    print(f"[DONE] Newly applied: {applied} out of {total_pending} Easy Apply jobs (Total in CSV: {len(df)})")

if __name__ == "__main__":
    main()

