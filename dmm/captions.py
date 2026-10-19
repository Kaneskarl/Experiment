"""Offline DMM drafts assembled only from supplied event facts."""

from datetime import date

FOOTER = ("Damdamag Misyon Montanyosa is the Official Online News Portal of the "
          "Mountain Provinces Mission of the Seventh-day Adventists.")
HASHTAGS = "#damdamagmisyonmontanyosa #adventistmontanyosa #mpmlocalnewsprogram"


def make_caption(event: dict, style: str = "album", photo_caption: str = "",
                 include_footer: bool = True, include_credit: bool = True) -> dict:
    missing = []
    for key, label in [("venue", "Venue / location"), ("organizer", "Organizer"),
                       ("activities", "What actually happened"), ("purpose", "Event purpose")]:
        if not event.get(key, "").strip():
            missing.append(label)
    when = date.fromisoformat(event["date"]).strftime("%B %d, %Y").replace(" 0", " ")
    name = event["name"].strip()
    place = event.get("venue", "").strip()
    theme = event.get("theme", "").strip()
    lines = [name, ""]
    if style == "photo":
        if not photo_caption.strip():
            missing.append("A factual description of this photo")
        else:
            lines += [photo_caption.strip(), ""]
        lines += [f"{when}" + (f" | {place}" if place else ""), ""]
    else:
        lines += [f"{when}" + (f" | {place}" if place else ""), ""]
        if theme:
            lines += [f'Theme: “{theme}”', ""]
        organizer = event.get("organizer", "").strip()
        if organizer:
            lines += [f"Organized by {organizer}.", ""]
        # Preserve the user's wording; do not infer activities, spiritual outcomes, or quotes.
        for key in ("activities", "purpose", "outcomes"):
            value = event.get(key, "").strip()
            if value:
                lines += [value, ""]
    credit = event.get("photographer", "").strip()
    if include_credit and credit:
        lines += [f"Photos: {credit}" if style == "album" else f"Photo: {credit}", ""]
    if include_footer:
        lines += [FOOTER, "", HASHTAGS]
    return {"text": "\n".join(lines).strip(), "missing": missing,
            "notice": "Offline template draft. Confirm names, dates, claims, and permissions before publication."}
