import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ROOT = Path(__file__).parent
DATA = ROOT / "data"
BASE = "https://switch-software-compatibility.nintendo.com/en-US/details/"


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

        # Look only at the text between the update date and
        # the next known section of the Nintendo page.
        after_update = t[update_date_match.end():].strip()

        next_section = re.search(
            r"\s+(?:View Product Information|Users Interact|Nintendo\.com|"
            r"Terms of Use|Nintendo Privacy Policy|Region Selector|© Nintendo)",
            after_update,
            re.IGNORECASE
        )

        if next_section:
            update_area = after_update[:next_section.start()].strip()
        else:
            update_area = after_update.strip()

        # A genuine update message ends with a period.
        # If there is no period, Nintendo has not provided
        # a separate update message.
        message_match = re.match(
            r"(.+?\.)\s*$",
            update_area
        )

        if message_match:
            possible_message = message_match.group(1).strip()

            # Do not treat content-rating descriptors as an update message.
            rating_only = (
                "," in possible_message
                and not re.search(r"\bissues?\b|\bproblems?\b|\bexperience\b|\bupdate\b|\bresolved\b",
                                  possible_message,
                                  re.IGNORECASE)
            )

            if not rating_only:
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
        result["text_sha256"] = hashlib.sha256(
            text.encode()
        ).hexdigest()
        result["page_text"] = text

    except PlaywrightTimeoutError as e:
        result["status"] = "Fetch error"
        result["error"] = str(e)

    return result


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

            if previous and (
                previous.get("status") != item.get("status")
                or previous.get("text_sha256") != item.get("text_sha256")
            ):
                events.append({
                    "type": "changed",
                    "title": item["title"],
                    "title_id": item["title_id"],
                    "date": item["checked_at"],
                    "old_status": previous.get("status"),
                    "new_status": item.get("status"),
                })

            elif not previous:
                events.append({
                    "type": "first_seen",
                    "title": item["title"],
                    "title_id": item["title_id"],
                    "date": item["checked_at"],
                    "old_status": None,
                    "new_status": item.get("status"),
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
