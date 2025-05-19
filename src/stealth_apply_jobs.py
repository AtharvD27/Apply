import os
import sys
import random
import time
import logging
import yaml
import pandas as pd
from typing import List
from pathlib import Path
from datetime import datetime

# Selenium / stealth ---------------------------------------------
from undetected_chromedriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException

# --- CONFIG ------------------------------------------------------
def load_config(path="config/apply_job_config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config()

DELAY = config["delay"]
CSV_FILE = config["main_csv_file"]
EMAIL = os.getenv("APPLY_EMAIL") or config["email"]
PASSWORD = os.getenv("APPLY_PASSWORD") or config["password"]
DRIVER_PATH = config.get("driver_path", "/usr/local/bin/chromedriver")
LOG_DIR = Path(config.get("log_dir", "output/logs"))

# ====== Logging ======
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOG_DIR / f"stealth_apply_job_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    filename=str(log_filename),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()


USER_AGENTS: List[str] = [
    # add a handful of recent, real desktop UA strings
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# ----------------------------------------------------------------

def human_delay(base: float = 2.0, jitter: float = 0.6):
    """Sleep for N( base, jitter^2 ) seconds – never negative."""
    time.sleep(max(0.05, random.normalvariate(base, jitter)))


def wiggle_mouse(driver):
    """Tiny mouse move to generate real DOM events."""
    body = driver.find_element(By.TAG_NAME, "body")
    actions = ActionChains(driver)
    dx, dy = random.randint(10, 400), random.randint(10, 400)
    actions.move_to_element_with_offset(body, dx, dy).pause(random.random() / 2).perform()


def get_stealth_driver(headless: bool = True):
    opts = ChromeOptions()
    if headless:
        # new headless mode mimics full Chrome better
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    # match GitHub runner Chrome version (136)
    return Chrome(options=opts, version_main=136)


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

        logger.info(f"APPLIED: {job_title} - {job_link}")
        print(f"APPLIED: {job_title} - {job_link}")
        return "Applied"

    except Exception as e:
        logger.error(f"FAILED to apply for {job_title} - {job_link}: {e}")
        print(f"FAILED to apply for {job_title} - {job_link}")
        return "Failed"

# ----------------------------------------------------------------

def main(process_failed: bool = False):
    # --- Get driver ------------------------------------------------
    driver = get_stealth_driver(headless=True)

    df = pd.read_csv(CSV_FILE)

    # 1. Filter only Easy Apply jobs
    easy_apply_df = df[df["apply_text"].str.strip().str.lower() == "easy apply"].copy()

    # 2. Further filter to only Pending (or Failed if specified)
    status_to_process = ["pending"]
    if process_failed:
        status_to_process.append("failed")

    pending_df = easy_apply_df[easy_apply_df["status"].str.lower().isin(status_to_process)].copy()

    if pending_df.empty:
        logger.info("✅ No new jobs to apply. Exiting early.")
        print("✅ No new jobs to apply. Exiting early.")
        return

    try:
        login_to_dice(driver, EMAIL, PASSWORD, DELAY)
        human_delay(3)

        # 3. Decide how many to apply this run (50‑100 random)
        target = random.randint(50, 100)
        n_to_apply = min(target, len(pending_df))
        if n_to_apply < len(pending_df):
            pending_df = pending_df.sample(n=n_to_apply, random_state=None)
        logger.info(f"[INFO] Will attempt {n_to_apply} job(s) this run (target {target}, available {len(pending_df)})")

        # 4. Iterate applications
        results = []
        for _, row in pending_df.iterrows():
            human_delay(random.uniform(4, 8))
            wiggle_mouse(driver)
            try:
                result = easy_apply(driver, row["link"], row["title"])
            except Exception as exc:
                logger.exception(exc)
                result = "Failed"
            results.append(result)
            human_delay(random.uniform(2, 4))

        applied = results.count("Applied")

        # 5. Update DataFrame in bulk
        easy_apply_df.loc[pending_df.index, "status"] = results

        # 6. Re‑merge & sort
        df_remaining = df.drop(easy_apply_df.index)
        df_combined = pd.concat([df_remaining, easy_apply_df], ignore_index=True)
        df_combined["status"] = pd.Categorical(df_combined["status"], categories=["Pending", "Applied", "Failed"], ordered=True)
        df_combined = df_combined.sort_values(by="status").reset_index(drop=True)

        # 7. Atomic CSV write
        df_combined.to_csv(CSV_FILE, index=False)

        logger.info(f"[DONE] Newly applied: {applied} out of {len(pending_df)} chosen (Total CSV rows: {len(df)})")
        print(f"[DONE] Newly applied: {applied} out of {len(pending_df)} chosen (Total CSV rows: {len(df)})")
    finally:
        driver.quit()

    # propagate success/failure to CI if needed
    if applied == 0:
        sys.exit(1)


if __name__ == "__main__":
    main(process_failed=False)
