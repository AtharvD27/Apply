# main.py
from stealth_scraper import main as run_scraper
import json
import pandas as pd
import os
import yaml

def load_config(path="config/scraper_config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def filter_relevant_jobs(config):
    input_csv = config["main_csv_file"]
    output_csv = config["filtered_csv_file"]

    with open("relevant_titles.json", "r") as f:
        relevant_titles = json.load(f)["titles"]

    df_new = pd.read_csv(input_csv)
    mask = df_new["title"].fillna("").str.lower().apply(
        lambda title: any(keyword in title for keyword in relevant_titles)
    )
    df_filtered = df_new[mask]

    if os.path.exists(output_csv):
        df_old = pd.read_csv(output_csv)
        existing_links = set(zip(df_old["link"], df_old.get("date_posted", pd.Series([""] * len(df_old)))))
        df_combined = pd.concat([df_old, df_filtered], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["link", "date_posted"], keep="first")
    else:
        df_combined = df_filtered
        existing_links = set()

    if "status" in df_combined.columns:
        df_combined["status"] = pd.Categorical(df_combined["status"], categories=["Pending", "Applied", "Failed"], ordered=True)
        df_combined = df_combined.sort_values("status")

    df_combined.to_csv(output_csv, index=False)

    new_pending_jobs = df_filtered[
        (~df_filtered[["link", "date_posted"]].apply(tuple, axis=1).isin(existing_links)) &
        (df_filtered["status"].str.lower() == "pending")
    ]
    print(f"[FILTERED] Merged & saved new {len(new_pending_jobs)} relevant *pending* jobs to {output_csv}")

if __name__ == "__main__":
    config = load_config()
    run_scraper()
    filter_relevant_jobs(config)
