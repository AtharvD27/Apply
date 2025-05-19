import os
import random
import time
import logging
import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Set, Tuple

import pandas as pd

# ── Selenium / Stealth ───────────────────────────────────────────
from undetected_chromedriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ── CONFIG & CONSTANTS ───────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config("config/scraper_config.yaml")
BASE_URL: str = os.getenv("BASE_URL") or config["base_url"]
CSV_FILE: str = config["main_csv_file"]
QUERY_FILE: str = config["query_file"]
MAX_PAGES: int = config.get("max_pages", 20)
DELAY_WAIT: int = config.get("delay", 6)

# Human‑style pacing
MIN_PAGE_DELAY = float(config.get("min_page_delay", 2))
MAX_PAGE_DELAY = float(config.get("max_page_delay", 4))

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# ── Logging ──────────────────────────────────────────────────────
log_dir = Path(config.get("log_dir", "output/logs"))
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / f"dice_scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    filename=str(log_path),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("dice_scraper")
logger.addHandler(logging.StreamHandler())  # echo to console

# ── Stealth helpers ──────────────────────────────────────────────

def human_delay(base: float = 2.0, jitter: float = 0.7):
    """Sleep like a human: N(base, jitter²) seconds (never < 0.1)."""
    time.sleep(max(0.1, random.normalvariate(base, jitter)))


def wiggle_mouse(driver):
    """Small random cursor move to generate genuine mouse events."""
    body = driver.find_element(By.TAG_NAME, "body")
    ActionChains(driver).move_to_element_with_offset(
        body,
        random.randint(5, 400),
        random.randint(5, 400),
    ).pause(random.random() / 2).perform()


def get_stealth_driver(headless: bool = True):
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")

    # Use the manually installed Chrome 136 in the GitHub runner
    opts.binary_location = "/opt/chrome/chrome"

    driver_path = config.get("driver_path", "/usr/local/bin/chromedriver")
    driver = Chrome(options=opts, driver_executable_path=driver_path, version_main=136)
    driver.implicitly_wait(3)
    return driver

# ── Scraper core ────────────────────────────────────────────────

def scrape_query(driver,query: str,seen_links: Set[Tuple[str, str]]) -> list:
    
    """Scrape all pages for a single search query and return job dicts."""
    new_jobs = []
    for page in range(1, MAX_PAGES + 1):
        url = BASE_URL.format(query=query.replace(" ", "+"), page=page)
        logger.info(f"Query: {query} | Page: {page}")
        print(f"Query: {query} | Page: {page}")

        try:
            driver.get(url)
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
            logger.warning(f"Timeout on: {url}")
            print(f"Timeout on: {url}")
            break

        # ── Process each card ────────────────────────────────────
        for card in job_cards:
            try:
                job_link_el = card.find_element(By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']")
                job_link = job_link_el.get_attribute("href")
                meta_elems = card.find_elements(By.CSS_SELECTOR, "p.text-sm.font-normal.text-zinc-600")
                location = meta_elems[0].text.strip() if meta_elems else "N/A"
                posted_date = meta_elems[2].text.strip() if len(meta_elems) > 2 else "N/A"

                # dedup on link + date
                if (job_link, posted_date) in seen_links:
                    continue
                seen_links.add((job_link, posted_date))

                # core fields
                job_title = job_link_el.text.strip()
                company_el = card.find_elements(By.CSS_SELECTOR, "p.line-clamp-2.text-sm")
                company = company_el[0].text.strip() if company_el else "N/A"
                
                desc = (
                    card.find_element(By.CSS_SELECTOR, "div.mt-2 p").text.strip()
                    if card.find_elements(By.CSS_SELECTOR, "div.mt-2 p")
                    else ""
                )

                def extract_tag(label_id: str) -> str:
                    try:
                        return card.find_element(By.CSS_SELECTOR, f"div[aria-labelledby='{label_id}']").text.strip()
                    except NoSuchElementException:
                        return ""

                job_type = extract_tag("employmentType-label")
                salary = extract_tag("salary-label")

                apply_text = (
                    card.find_element(By.XPATH, ".//div[contains(@class, 'gap-1.5')]/a").text.strip()
                    if card.find_elements(By.XPATH, ".//div[contains(@class, 'gap-1.5')]/a")
                    else ""
                )

                new_jobs.append(
                    {
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
                    }
                )

                logger.info(f"[+] FOUND — {job_title}")
                print(f"[+] FOUND — {job_title}")
                
            except Exception as exc:
                logger.error(f"Error parsing card: {exc}")

        # human‑like behaviour between pages
        wiggle_mouse(driver)
        human_delay(random.uniform(MIN_PAGE_DELAY, MAX_PAGE_DELAY))
        
    logger.info(f"Total pages scanned for query '{query}': {total_pages_scraped}")
    print(f"Total pages scanned for query '{query}': {total_pages_scraped}")
    logger.info(f"Total new jobs found for query '{query}': {len(new_jobs)}")
    print(f"Total new jobs found for query '{query}': {len(new_jobs)}")

    return new_jobs

# ── Main entrypoint ─────────────────────────────────────────────

def main():
    driver = get_stealth_driver(headless=True)
    try:
        # load existing
        if os.path.exists(CSV_FILE):
            df_existing = pd.read_csv(CSV_FILE)
            seen_links: Set[Tuple[str, str]] = set(
                zip(df_existing["link"], df_existing.get("date_posted", pd.Series(["" for _ in range(len(df_existing))])))
            )
        else:
            df_existing = pd.DataFrame()
            seen_links = set()

        with open(QUERY_FILE, "r") as f:
            queries = [q.strip() for q in f if q.strip()]

        all_jobs = []
        for q in queries:
            all_jobs.extend(scrape_query(driver, q, seen_links))

        df_new = pd.DataFrame(all_jobs)
        if not df_new.empty:
            df_new["status"] = "Pending"
            df_new["date_added"] = pd.to_datetime(df_new["date_added"], format="%m/%d/%Y")

        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.drop_duplicates(subset=["link", "date_posted"], keep="first", inplace=True)
        df_combined.to_csv(CSV_FILE, index=False)

        logger.info(f"✅ Scrape done. New: {len(df_new)} | Total rows: {len(df_combined)}")
        print(f"✅ Scrape done. New: {len(df_new)} | Total rows: {len(df_combined)}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
