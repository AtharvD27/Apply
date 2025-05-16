import os
import pandas as pd
import logging
import yaml
from dotenv import load_dotenv
from pathlib import Path
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ====== CONFIG ======
def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config("config/scraper_config.yaml")
BASE_URL = os.getenv("BASE_URL") or config["base_url"]

# ====== Logging ======
log_dir = Path(config.get("log_dir", "output/logs"))
log_dir.mkdir(parents=True, exist_ok=True)
log_filename = log_dir / f"dice_scrapper_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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

    # ✅ Use stable headless mode compatible with CI
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # ✅ Use manually installed Chrome 136
    chrome_options.binary_location = "/opt/chrome/chrome"

    # ❌ DO NOT set user-data-dir — it causes session issues on GitHub
    # chrome_options.add_argument("--user-data-dir=/tmp/somepath") ← REMOVE THIS LINE

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

def scrape_query(driver, query, seen_links, MAX_PAGES, DELAY_WAIT):
    new_jobs = []
    total_pages_scraped = 0

    for page in range(1, MAX_PAGES + 1):
        search_url = BASE_URL.format(query=query.replace(" ", "+"), page=page)
        logger.info(f"Query: {query} | Page: {page}")
        print(f"Query: {query} | Page: {page}")

        try:
            driver.get(search_url)
            WebDriverWait(driver, DELAY_WAIT).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-job-guid]"))
            )
            job_cards = driver.find_elements(By.CSS_SELECTOR, "div[data-job-guid]")
            if not job_cards:
                logger.info("No job cards found — breaking pagination.")
                print("No job cards found — breaking pagination.")
                break
            total_pages_scraped += 1
        except TimeoutException:
            logger.warning(f"Timeout on: {search_url}")
            print(f"Timeout on: {search_url}")
            break

        for card in job_cards:
            try:
                job_link_el = card.find_element(By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
                job_link = job_link_el.get_attribute("href")

                meta_elems = card.find_elements(By.CSS_SELECTOR, "p.text-sm.font-normal.text-zinc-600")
                location = meta_elems[0].text.strip() if len(meta_elems) > 0 else "N/A"
                posted_date = meta_elems[2].text.strip() if len(meta_elems) > 2 else "N/A"

                if (job_link, posted_date) in seen_links:
                    continue
                seen_links.add((job_link, posted_date))

                job_title = job_link_el.text.strip()
                company_el = card.find_elements(By.CSS_SELECTOR, "p.line-clamp-2.text-sm")
                company = company_el[0].text.strip() if company_el else "N/A"

                try:
                    desc = card.find_element(By.CSS_SELECTOR, "div.mt-2 p").text.strip()
                except NoSuchElementException:
                    desc = ""

                def extract_tag(label_id):
                    try:
                        return card.find_element(By.CSS_SELECTOR, f"div[aria-labelledby='{label_id}']").text.strip()
                    except NoSuchElementException:
                        return ""

                job_type = extract_tag("employmentType-label")
                salary = extract_tag("salary-label")

                # Extract Apply Now button text
                try:
                    apply_button_elem = card.find_element(By.XPATH, ".//div[contains(@class, 'gap-1.5')]/a")
                    apply_text = apply_button_elem.text.strip()
                except NoSuchElementException:
                    apply_text = ""

                new_jobs.append({
                    "title": job_title,
                    "company": company,
                    "link": job_link,
                    "description": desc,
                    "location": location,
                    "date_added": datetime.now().strftime("%m/%d/%Y"),
                    "date_posted": posted_date,
                    "job_type": job_type,
                    "salary": salary,
                    "apply_text": apply_text,
                })

                logger.info(f"[+] FOUND — {job_title}")
                print(f"[+] FOUND — {job_title}")

            except Exception as e:
                logger.error(f"Job card scrape failed: {e}")
                print(f"Job card scrape failed: {e}")

    logger.info(f"Total pages scanned for query '{query}': {total_pages_scraped}")
    print(f"Total pages scanned for query '{query}': {total_pages_scraped}")
    logger.info(f"Total new jobs found for query '{query}': {len(new_jobs)}")
    print(f"Total new jobs found for query '{query}': {len(new_jobs)}")
    return new_jobs

def main():
    DELAY_WAIT = config["delay"]
    CSV_FILE = config["main_csv_file"]
    EMAIL = os.getenv("SCRAPER_EMAIL") or config["email"]
    PASSWORD = os.getenv("SCRAPER_PASSWORD") or config["password"]
    MAX_PAGES = config.get("max_pages", 20)
    QUERY_FILE = config["query_file"]

    driver = get_driver()
    login_to_dice(driver, EMAIL, PASSWORD, DELAY_WAIT)

    if os.path.exists(CSV_FILE):
        df_existing = pd.read_csv(CSV_FILE)
    else:
        df_existing = pd.DataFrame()

    seen_links = set(
        zip(df_existing["link"], df_existing.get("date_posted", pd.Series([""] * len(df_existing))))
    ) if not df_existing.empty else set()

    with open(QUERY_FILE, "r") as f:
        queries = [line.strip() for line in f if line.strip()]

    all_results = []
    for query in queries:
        all_results.extend(scrape_query(driver, query, seen_links, MAX_PAGES, DELAY_WAIT))

    df_new = pd.DataFrame(all_results)
    if not df_new.empty:
        df_new["status"] = "Pending"
        df_new["date_added"] = pd.to_datetime(df_new["date_added"], format="%m/%d/%Y")

    df_combined = pd.concat([df_existing, df_new], ignore_index=True).drop_duplicates(subset=["link", "date_posted"], keep="first")
    df_combined.to_csv(CSV_FILE, index=False)
    
    if not df_existing.empty and not df_new.empty:
        reposted_jobs = df_new.merge(df_existing, on="link", suffixes=("_new", "_old"))
        reposted_jobs = reposted_jobs[
            reposted_jobs["date_posted_new"] != reposted_jobs["date_posted_old"]
        ]
        if not reposted_jobs.empty:
            reposted_jobs_out = reposted_jobs[
                ["title_new", "company_new", "link", "date_posted_new", "date_posted_old"]
            ].rename(columns={
                "title_new": "title",
                "company_new": "company",
                "date_posted_new": "new_posted_date",
                "date_posted_old": "previous_posted_date"
            })
            reposted_jobs_out.to_csv("output/reposted_jobs.csv", index=False)
            logger.info(f"[🔁] Reposted jobs saved: {len(reposted_jobs_out)}")
            print(f"[🔁] Reposted jobs saved: {len(reposted_jobs_out)}")

    # Save log summary
    log_file = log_dir / f"save_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    unique_added = len(df_combined) - len(df_existing) if not df_existing.empty else len(df_combined)

    with open(log_file, "w") as f:
        f.write(f"✅ Save log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"New unique jobs added: {unique_added}\n")
        f.write(f"Total jobs saved: {len(df_combined)}\n")

    logger.info(f"[✅] Scraping complete. Total new jobs saved: {len(df_new)}")
    print(f"[✅] Scraping complete. Total jobs saved: {len(df_new)}")
    driver.quit()

if __name__ == "__main__":
    main()
