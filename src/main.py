# main.py
from dice_scraper import main as run_dice_scraper
import json
import pandas as pd
import os
import yaml

def load_config(path="config.yaml"):
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
        df_combined = pd.concat([df_old, df_filtered], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["link", "date_posted"], keep="first")
    else:
        df_combined = df_filtered

    if "status" in df_combined.columns:
        df_combined["status"] = pd.Categorical(df_combined["status"], categories=["Pending", "Applied", "Failed"], ordered=True)
        df_combined = df_combined.sort_values("status")

    df_combined.to_csv(output_csv, index=False)
    print(f"[FILTERED] Merged & saved new {len(df_filtered)} relevant jobs to existing {output_csv}")

if __name__ == "__main__":
    config = load_config("config/scraper_config.yaml")
    run_dice_scraper()
    filter_relevant_jobs(config)
