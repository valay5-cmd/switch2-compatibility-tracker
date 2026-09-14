import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ROOT = Path(__file__).parent
DATA = ROOT / "data"
BASE = "https://switch-software-compatibility.nintendo.com/en-US/details/"

TRACKED_FIELDS = [
    "status",
    "behavior",
    "update_date",
    "update_message",
]


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )


def normalize(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_compatibility(text):
    t = normalize(text)

    result = {
        "status": "Unknown",
        "behavior": None,
        "update_date": None,
        "update_message": None,
    }

    # Extract compatibility status and behavior.
    compatibility_match = re.search(
        r"Nintendo Switch 2 Compatibility\s+"
        r"(Supported|Unsupported|Compatible)"
        r"\s+[–-]\s+(.+?\.)",
        t,
        re.IGNORECASE
    )

    if compatibility_match:
        result["status"] = compatibility_match.group(1).capitalize()
        result["behavior"] = compatibility_match.group(2).strip()

    # Extract update date.
    update_date_match = re.search(
        r"Update\s+(\d{2}/\d{2}/\d{4})",
        t,
        re.IGNORECASE
    )

    if update_date_match:
        result["update_date"] = update_date_match.group(1)

        # Everything after the update date.
        after_update = t[update_date_match.end():].strip()

        # Nintendo places the content-rating information after the
        # update message. The product-information section comes after
        # those ratings. We only need the portion before that section.
        product_match = re.search(
            r"\s+View Product Information\b",
            after_update,
            re.IGNORECASE
        )

        if product_match:
            update_area = after_update[:product_match.start()].strip()
        else:
            update_area = after_update

        # Remove trailing content-rating information when it follows
        # a genuine update message.
        #
        # Examples:
        #   "Previously identified issues have been resolved with an update.
        #    Blood and Gore, Language, Partial Nudity, Violence, Users Interact"
        #
        #   "Users may experience audio problems in some areas.
        #    Users Interact"
        #
        #   "Fantasy Violence, Mild Blood, Tobacco Reference"
        #
        # We identify the first complete sentence. If the text before
        # that sentence is just rating information, there is no message.
        sentence_match = re.match(
            r"(.+?\.)",
            update_area
        )

        if sentence_match:
            possible_message = sentence_match.group(1).strip()

            # A message should contain normal sentence wording.
            # A rating-only block generally consists of short descriptor
            # phrases separated by commas and does not contain these
            # sentence-style indicators.
            rating_indicators = [
                "Blood and Gore",
                "Fantasy Violence",
                "Mild Blood",
                "Mild Suggestive Themes",
                "Language",
                "Partial Nudity",
                "Tobacco Reference",
                "Use of Alcohol",
                "Violence",
                "Users Interact",
            ]

            is_exact_rating = possible_message in rating_indicators

            if not is_exact_rating:
                result["update_message"] = possible_message

    return result


def check(page, game):
    title_id = game["title_id"].upper()
    url = BASE + title_id

    result = {
        **game,
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=45000
        )

        page.wait_for_timeout(2500)

        text = normalize(
            page.locator("body").inner_text(timeout=10000)
        )

        compatibility = parse_compatibility(text)

        result.update(compatibility)

        # Keep this hash for debugging/reference.
        # It is NOT used for compatibility change detection.
        result["text_sha256"] = hashlib.sha256(
            text.encode()
        ).hexdigest()

        result["page_text"] = text

    except PlaywrightTimeoutError as e:
        result["status"] = "Fetch error"
        result["error"] = str(e)

    return result


def find_changes(previous, current):
    changes = []

    for field in TRACKED_FIELDS:
        old_value = previous.get(field)
        new_value = current.get(field)

        if old_value != new_value:
            changes.append({
                "field": field,
                "old": old_value,
                "new": new_value,
            })

    return changes


def main():
    games = load(DATA / "games.json", [])
    old = load(DATA / "current.json", [])
    history = load(DATA / "history.json", [])

    old_by_id = {
        g["title_id"]: g
        for g in old
    }

    current = []
    events = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-US")

        for game in games:
            print("Checking", game["title"])

            item = check(page, game)
            current.append(item)

            previous = old_by_id.get(game["title_id"])

            if previous:
                changes = find_changes(previous, item)

                if changes:
                    events.append({
                        "type": "changed",
                        "title": item["title"],
                        "title_id": item["title_id"],
                        "date": item["checked_at"],
                        "changes": changes,
                    })

            else:
                events.append({
                    "type": "first_seen",
                    "title": item["title"],
                    "title_id": item["title_id"],
                    "date": item["checked_at"],
                    "changes": [
                        {
                            "field": field,
                            "old": None,
                            "new": item.get(field),
                        }
                        for field in TRACKED_FIELDS
                    ],
                })

        browser.close()

    history.extend(events)

    save(DATA / "current.json", current)
    save(DATA / "history.json", history)

    print(
        f"Checked {len(current)} games; "
        f"{len(events)} new events."
    )


if __name__ == "__main__":
    main()
