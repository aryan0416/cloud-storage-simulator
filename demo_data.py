"""
demo_data.py
------------
Owner-only "Load demo data" feature.

Sample files are GENERATED IN CODE (nothing pre-made is shipped in the repo)
and then uploaded through the normal storage.upload_file function, so they
follow exactly the same rules as user uploads (quota, sanitising, logging).
"""

import csv
import io
import random

from PIL import Image, ImageDraw

import auth
import backup
import config
import database
import storage


def make_text_file() -> bytes:
    text = (
        "Cloud Storage and Backup Management Simulator\n"
        "=============================================\n\n"
        "This is a demo text file created by the simulator.\n"
        "It was uploaded to the Hot tier with LRS redundancy.\n\n"
        "Hot tier  -> frequently accessed data\n"
        "Cool tier -> infrequently accessed data (30-day minimum)\n"
        "Cold tier -> rarely accessed data (90-day minimum)\n"
        "Archive   -> offline long-term data (180-day minimum)\n"
    )
    return text.encode("utf-8")


def make_csv_file() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["month", "region", "storage_gb", "requests"])
    random.seed(42)                                    # same output every time
    for month in ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]:
        for region in ["Central India", "South India"]:
            writer.writerow([month, region, random.randint(50, 500), random.randint(1000, 9000)])
    return buffer.getvalue().encode("utf-8")


def make_png_chart() -> bytes:
    """Draw a small bar chart of the illustrative tier prices with Pillow."""
    width, height = 480, 300
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 12), "Illustrative price per GB/month (USD)", fill=(0, 51, 102))

    tiers = list(config.TIERS.items())
    max_price = max(t["price_per_gb_month"] for _, t in tiers)
    colours = [(0, 90, 158), (0, 120, 212), (80, 160, 230), (150, 195, 240)]
    bar_width, gap, base_y, chart_height = 80, 30, 260, 200

    for index, (name, tier) in enumerate(tiers):
        x0 = 40 + index * (bar_width + gap)
        bar_h = int(chart_height * tier["price_per_gb_month"] / max_price)
        draw.rectangle([x0, base_y - bar_h, x0 + bar_width, base_y], fill=colours[index])
        draw.text((x0 + 5, base_y + 8), name, fill="black")
        draw.text((x0 + 5, base_y - bar_h - 14), f"${tier['price_per_gb_month']}", fill="black")
    draw.line([30, base_y, width - 20, base_y], fill="black", width=1)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def load_demo_data(user: dict) -> list[str]:
    """Generate and upload three sample files into different tiers + one backup."""
    auth.require_permission(user, "load_demo_data")
    samples = [
        ("demo_readme.txt", make_text_file(), "Hot", "LRS"),
        ("demo_usage_report.csv", make_csv_file(), "Cool", "GRS"),
        ("demo_tier_prices.png", make_png_chart(), "Cold", "GRS"),
    ]
    created = []
    first_file_id = None
    for name, data, tier, redundancy in samples:
        file_id = storage.upload_file(data, name, tier, redundancy, user, action="Upload (demo)")
        first_file_id = first_file_id or file_id
        created.append(f"{name} ({tier}, {redundancy})")

    backup.create_backup(first_file_id, user)
    database.log_activity(user["username"], user["role"], "Demo data loaded",
                          details=f"{len(samples)} files uploaded and 1 backup created")
    return created
