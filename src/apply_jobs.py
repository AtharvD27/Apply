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
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # ✅ Use Chrome 136 explicitly
    chrome_options.binary_location = "/opt/chrome/chrome"

    # ✅ Set a unique temp user-data-dir to avoid session conflicts
    chrome_options.add_argument(f"--user-data-dir={tempfile.mkdtemp()}")

    driver_path = config.get("driver_path", "/usr/local/bin/chromedriver")
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.implicitly_wait(3)
    return driver

def login_to_dice(driver):
    logger.info("Logging into Dice...")
    print("Logging into Dice...")
    driver.get("https://www.dice.com/dashboard/login")
    time.sleep(5)
    driver.find_element(By.NAME, "email").send_keys(EMAIL)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    time.sleep(5)
    driver.find_element(By.NAME, "password").send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    time.sleep(5)
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

        logger.info(f"APPLIED: {job_title} — {job_link}")
        print(f"APPLIED: {job_title}")
        return "Applied"

    except (NoSuchElementException, ElementClickInterceptedException) as e:
        logger.error(f"FAILED to apply for {job_title}: {e}")
        print(f"FAILED to apply for {job_title}")
        return "Failed"

def main():
    driver = get_driver()
    login_to_dice(driver)

    df = pd.read_csv(CSV_FILE)
    applied = 0

    for idx, row in df.iterrows():
        if str(row.get("status", "")).lower() == "applied":
            continue
        result = easy_apply(driver, row["link"], row["title"])
        df.at[idx, "status"] = result
        if result == "Applied":
            applied += 1

    df.to_csv(CSV_FILE, index=False)
    driver.quit()

    logger.info(f"[DONE] Applied to {applied} jobs out of {len(df)} total.")
    print(f"[DONE] Applied to {applied} jobs out of {len(df)} total.")

if __name__ == "__main__":
    main()
