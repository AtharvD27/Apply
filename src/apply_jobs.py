import os
import time
import yaml
import logging
import random
from datetime import datetime
import pandas as pd
from selenium import webdriver
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from dotenv import load_dotenv

# ====== CONFIG ======
def load_config(path="config/apply_job_config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)
    
def str2bool(s): return str(s).lower() in {"1","true","yes","y"}

config = load_config()
load_dotenv()

DELAY = config["delay"]
CSV_FILE = config["main_csv_file"]
EMAIL = os.getenv("APPLY_EMAIL") or config["email"]
PASSWORD = os.getenv("APPLY_PASSWORD") or config["password"]
DRIVER_PATH = config.get("driver_path", "/usr/local/bin/chromedriver")
LOG_DIR = Path(config.get("log_dir", "output/logs"))
PROCESS_FAILED = str2bool(os.getenv("APPLY_PROCESS_FAILED", "false"))

# ====== Logging ======
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOG_DIR / f"apply_job_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    filename=str(log_filename),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()

def get_driver():
    chrome_options = Options()

    # ✅ Use stable headless mode compatible with CI
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # ✅ Use Chrome 136 installed via CI
    chrome_options.binary_location = "/opt/chrome/chrome"

    driver_path = config.get("driver_path", "/usr/local/bin/chromedriver")
    service = Service(driver_path)

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.implicitly_wait(3)
    return driver


def login_to_dice(driver, EMAIL, PASSWORD, DELAY_WAIT):
    logger.info("Logging into Dice...")
    print("Logging into Dice...")

    driver.get("https://www.dice.com/dashboard/login")
    
    WebDriverWait(driver, DELAY_WAIT).until(
        EC.presence_of_element_located((By.NAME, "email"))
    ).send_keys(EMAIL)

    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    WebDriverWait(driver, DELAY_WAIT).until(
        EC.presence_of_element_located((By.NAME, "password"))
    ).send_keys(PASSWORD)

    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    WebDriverWait(driver, DELAY_WAIT).until(EC.url_contains("dashboard"))
    logger.info("Login successful.")
    print("Login successful.")

def easy_apply(driver, job_link, job_title):
    try:
        driver.get(job_link)
        time.sleep(DELAY)

        '''
        # Save the job
        try:
            # Step 1: Get outer shadow root of dhi-job-search-save-job
            save_host = driver.find_element(By.CSS_SELECTOR, "dhi-job-search-save-job")
            outer_shadow = driver.execute_script("return arguments[0].shadowRoot", save_host)

            # Step 2: Get shadow root of inner seds-button
            seds_button = outer_shadow.find_element(By.CSS_SELECTOR, "seds-button")
            inner_shadow = driver.execute_script("return arguments[0].shadowRoot", seds_button)

            # Step 3: Read text from the <button>
            button = inner_shadow.find_element(By.CSS_SELECTOR, "button")
            save_text = button.text.strip().lower()

            if "saved" in save_text:
                logger.info(f"SKIPPED Save (already saved): {job_title}")
                print(f"SKIPPED Save (already saved): {job_title}")
            else:
                button.click()
                logger.info(f"SAVED: {job_title}")
                print(f"SAVED: {job_title}")
                time.sleep(DELAY - 1)
        except Exception as e:
            logger.warning(f"Save logic failed for {job_title} — {e}")
            print(f"Save logic failed for {job_title}")
        '''

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
            logger.warning(f"Could not check application status for {job_title} — {e}")

        # Remove modal if blocking
        try:
            modal = driver.find_element(By.TAG_NAME, "login-dhi-modal")
            if modal.is_displayed():
                driver.execute_script("arguments[0].remove();", modal)
                time.sleep(1)
        except Exception:
            pass

        # Apply to the job
        try:
            apply_button = WebDriverWait(driver, DELAY).until(
                EC.presence_of_element_located((By.TAG_NAME, "apply-button-wc"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", apply_button)
            time.sleep(2)
            apply_button.click()
        except (TimeoutException, ElementNotInteractableException) as e:
            logger.error(f"Cannot click apply-button-wc for {job_title}: {e}")
            return "Failed"

        next_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-next')]")
        next_btn.click()
        time.sleep(DELAY - 2)

        final_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-next')]")
        final_btn.click()
        time.sleep(DELAY - 2)

        logger.info(f"APPLIED: {job_title}")
        print(f"APPLIED: {job_title}")
        return "Applied"

    except Exception as e:
        logger.error(f"FAILED to apply for {job_title} - {job_link}: {e}")
        print(f"FAILED to apply for {job_title} - {job_link}")
        return "Failed"


def main(process_failed=False):
    driver = get_driver()

    try:
        login_to_dice(driver, EMAIL, PASSWORD, DELAY)

        df = pd.read_csv(CSV_FILE)
        
        # 1. Filter only Easy Apply jobs
        easy_apply_df = df[df["apply_text"].str.strip().str.lower() == "easy apply"].copy()
        
        # 2. Further filter to only Pending (or Failed if specified)
        status_to_process = ["pending"]
        if process_failed:
            status_to_process.append("failed")

        pending_df = easy_apply_df[
            easy_apply_df["status"].str.lower().isin(status_to_process)
        ].copy()

        target_n = random.randint(50, 100)            # pick a target
        n_to_apply = min(target_n, len(pending_df))   # but don’t exceed available
        if n_to_apply < len(pending_df):
            pending_df = pending_df.sample(n=n_to_apply, random_state=None)

        logger.info(f"[INFO] Will attempt {n_to_apply} job(s) this run "
                    f"(requested {target_n}, available {len(df)})")
        print(f"[INFO] Will attempt {n_to_apply} job(s) this run "
            f"(requested {target_n}, available {len(df)})")
        
        logger.info(f"[INFO] Processing jobs with status: {status_to_process}")
        print(f"[INFO] Processing jobs with status: {status_to_process}")

        results = []

        for _, row in pending_df.iterrows():
            try:
                result = easy_apply(driver, row["link"], row["title"])
            except Exception as e:
                logger.error(f"Error applying for {row['title']} - {row['link']}: {e}")
                result = "Failed"
            results.append(result)

        easy_apply_df.loc[pending_df.index, "status"] = results
        applied = results.count("Applied")
        total_pending = len(pending_df)

        # 3. Merge updated Easy Apply section back into full df
        df_remaining = df.drop(easy_apply_df.index)
        df_combined = pd.concat([df_remaining, easy_apply_df], ignore_index=True)

        # Sort by status only
        df_combined["status"] = pd.Categorical(df_combined["status"], categories=["Pending", "Applied", "Failed"], ordered=True)
        df_combined = df_combined.sort_values(by="status").reset_index(drop=True)

        df_combined.to_csv(CSV_FILE, index=False)

        logger.info(f"[DONE] Newly applied: {applied} out of {total_pending} Easy Apply jobs (Total in CSV: {len(df)})")
        print(f"[DONE] Newly applied: {applied} out of {total_pending} Easy Apply jobs (Total in CSV: {len(df)})")
    
    finally:
        driver.quit()

if __name__ == "__main__":
    main(process_failed=PROCESS_FAILED)

