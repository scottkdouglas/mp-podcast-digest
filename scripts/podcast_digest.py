#!/usr/bin/env python3
"""
MP Podcast Digest -- daily summary pipeline for Restaurant Marketing Secrets.

Pipeline:
  1. Fetch the Libsyn RSS feed
  2. Compare latest GUID against state file
  3. If unchanged and not FORCE_RUN, exit silently
  4. Download the audio enclosure (handles .m4a or .mp3)
  5. Transcribe via faster-whisper (small.en, CPU int8)
  6. Build the system prompt by injecting exclusion rules from podcastexclusion.md
  7. Summarize via Anthropic Sonnet 4.6 (Claude does the cold-open / body
     splitting and the intro / Skool-promo trimming based on the exclusion rules)
  8. Email the summary to the team via Gmail SMTP (TLS, port 465)
  9. Update state file (only after successful email)

Configuration via environment variables:
  ANTHROPIC_API_KEY        Anthropic console key
  GMAIL_APP_PASSWORD       Google Workspace app password (16 chars, no spaces)
  GMAIL_FROM_ADDRESS       sender address (matches the app password account)
  TEAM_EMAIL_RECIPIENTS    comma-separated list of recipient addresses
  PODCAST_FEED_URL         Libsyn RSS feed URL
  STATE_FILE               path to last-seen.txt (relative to checkout root)
  EXCLUSION_FILE           path to podcastexclusion.md
  PROMPT_FILE              path to summary.md prompt
  FORCE_RUN                "true" to bypass the state-check short-circuit
  DRY_RUN                  "true" to skip email + state update; write to /tmp instead
"""

import logging
import os
import re
import smtplib
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import feedparser
import markdown
import requests
from faster_whisper import WhisperModel

LOG = logging.getLogger("mp-podcast-digest")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ---------- Config helpers ----------

def env(key: str, required: bool = True, default: str = "") -> str:
    val = os.environ.get(key, default)
    if required and not val:
        LOG.error("missing required env var: %s", key)
        sys.exit(1)
    return val


def env_bool(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in ("true", "1", "yes")


# ---------- Step 1-3: Feed + state ----------

def fetch_latest_episode(feed_url: str) -> dict:
    LOG.info("fetching feed: %s", feed_url)
    parsed = feedparser.parse(feed_url)
    if parsed.bozo:
        LOG.error("feed parse error: %s", parsed.bozo_exception)
        sys.exit(2)
    if not parsed.entries:
        LOG.error("feed has no episodes")
        sys.exit(2)
    entry = parsed.entries[0]
    enclosure_url = ""
    if getattr(entry, "enclosures", None):
        enclosure_url = entry.enclosures[0].get("href") or entry.enclosures[0].get("url", "")
    if not enclosure_url:
        for link in entry.get("links", []):
            if link.get("rel") == "enclosure":
                enclosure_url = link.get("href", "")
                break
    if not enclosure_url:
        LOG.error("latest episode has no audio enclosure")
        sys.exit(2)
    return {
        "guid": (entry.get("id") or entry.get("guid") or entry.get("link") or "").strip(),
        "title": entry.get("title", "(untitled)").strip(),
        "published": entry.get("published", "").strip(),
        "link": entry.get("link", "").strip(),
        "enclosure_url": enclosure_url,
    }


def already_processed(state_path: Path, guid: str) -> bool:
    if not state_path.exists():
        return False
    return state_path.read_text().strip() == guid


# ---------- Step 4: Download ----------

def download_audio(url: str, dest_dir: Path) -> Path:
    suffix = Path(urlparse(url).path).suffix or ".audio"
    dest = dest_dir / f"episode{suffix}"
    LOG.info("downloading: %s -> %s", url, dest)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
    LOG.info("downloaded %.1f MB", dest.stat().st_size / 1024 / 1024)
    return dest


# ---------- Step 5: Transcribe ----------

def transcribe(audio_path: Path) -> str:
    LOG.info("loading whisper model: small.en (cpu, int8)")
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    LOG.info("transcribing %s", audio_path.name)
    # initial_prompt primes Whisper with show-specific proper nouns it
    # would otherwise mis-transcribe. Confirmed in earlier dry runs:
    # without this, "Plapp" becomes "Platt" and "Skool" becomes "school"
    # (since Skool is intentionally misspelled and sounds identical).
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        initial_prompt=(
            "This is the Restaurant Marketing Secrets podcast hosted by "
            "Matt Plapp. He runs America's Best Restaurants (ABR) and a "
            "Skool community for independent restaurant owners."
        ),
    )
    text = " ".join(seg.text.strip() for seg in segments)
    LOG.info("transcript: %d chars, language=%s", len(text), info.language)
    return text


# ---------- Step 6: Build system prompt ----------

def load_exclusion_rules(path: Path) -> str:
    """Read the full exclusion-rules markdown file and return its text.
    The text is injected into the system prompt at the {EXCLUSION_RULES}
    placeholder so the model has the rules in context when summarizing.

    Editing podcastexclusion.md changes the trimming behavior with no
    code changes required."""
    if not path.exists():
        LOG.error("exclusion rules file not found at %s", path)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def parse_episode_metadata(raw_title: str, raw_published: str) -> tuple[str, str, str]:
    """
    Pull out the episode number, strip the redundant show-name+number suffix
    from the title, and format the publish date for human-readable subjects.

    Example input:
        raw_title    = "The Chains Have Stole Your Customers Attention - Restaurant Marketing Secrets - Episode 966"
        raw_published = "Tue, 07 Apr 2026 12:43:00 +0000"

    Returns:
        ("966", "The Chains Have Stole Your Customers Attention", "Apr 7, 2026")
    """
    from email.utils import parsedate_to_datetime

    ep_match = re.search(r"Episode\s+(\d+)", raw_title, re.IGNORECASE)
    episode_num = ep_match.group(1) if ep_match else "?"

    clean_title = re.sub(
        r"\s*-\s*Restaurant Marketing Secrets\s*-\s*Episode\s+\d+\s*$",
        "",
        raw_title,
        flags=re.IGNORECASE,
    ).strip()

    try:
        dt = parsedate_to_datetime(raw_published)
        # Build "Apr 7, 2026" without platform-dependent strftime quirks
        formatted_date = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except Exception:
        formatted_date = raw_published

    return episode_num, clean_title, formatted_date


# ---------- Step 7: Summarize ----------

def summarize(
    transcript: str,
    episode_title: str,
    prompt_path: Path,
    exclusion_rules: str,
    api_key: str,
) -> str:
    LOG.info("calling Anthropic API (claude-sonnet-4-6) for summary")
    template = prompt_path.read_text(encoding="utf-8")
    if "{EXCLUSION_RULES}" not in template:
        LOG.error("prompt template is missing the {EXCLUSION_RULES} placeholder")
        sys.exit(1)
    system = template.replace("{EXCLUSION_RULES}", exclusion_rules)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{
            "role": "user",
            "content": f"Episode title: {episode_title}\n\nTranscript:\n\n{transcript}",
        }],
    )
    return msg.content[0].text


# ---------- Step 8: Email ----------

def send_email(
    summary_md: str,
    subject: str,
    from_addr: str,
    app_password: str,
    recipients: list[str],
) -> None:
    LOG.info("sending email to %d recipient(s)", len(recipients))
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(summary_md)
    html_body = markdown.markdown(summary_md, extensions=["extra", "sane_lists"])
    msg.add_alternative(
        f"<!doctype html><html><body>{html_body}</body></html>",
        subtype="html",
    )
    # Gmail requires the app password with NO spaces.
    cleaned_password = app_password.replace(" ", "")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(from_addr, cleaned_password)
        smtp.send_message(msg)
    LOG.info("email sent")


# ---------- Main ----------

def main() -> int:
    feed_url = env("PODCAST_FEED_URL")
    state_path = Path(env("STATE_FILE"))
    exclusion_path = Path(env("EXCLUSION_FILE"))
    prompt_path = Path(env("PROMPT_FILE"))
    api_key = env("ANTHROPIC_API_KEY")
    gmail_password = env("GMAIL_APP_PASSWORD")
    gmail_from = env("GMAIL_FROM_ADDRESS")
    recipients = [r.strip() for r in env("TEAM_EMAIL_RECIPIENTS").split(",") if r.strip()]
    force_run = env_bool("FORCE_RUN")
    dry_run = env_bool("DRY_RUN")

    episode = fetch_latest_episode(feed_url)
    episode_num, clean_title, formatted_date = parse_episode_metadata(
        episode["title"], episode["published"]
    )
    subject = f"[MP's Podcast {episode_num}] {formatted_date} - {clean_title}"
    LOG.info("latest episode: %r (%s)", episode["title"], episode["guid"])
    LOG.info("subject will be: %s", subject)

    if already_processed(state_path, episode["guid"]) and not force_run:
        LOG.info("already processed; nothing to do")
        return 0

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = download_audio(episode["enclosure_url"], Path(tmpdir))
        raw_transcript = transcribe(audio_path)

    exclusion_rules = load_exclusion_rules(exclusion_path)
    LOG.info("loaded exclusion rules: %d chars", len(exclusion_rules))

    summary = summarize(raw_transcript, clean_title, prompt_path, exclusion_rules, api_key)
    LOG.info("summary: %d chars", len(summary))

    if episode["link"]:
        summary += f"\n\n---\n\n[Listen to this episode]({episode['link']})"

    if dry_run:
        Path("/tmp/summary.md").write_text(summary, encoding="utf-8")
        Path("/tmp/transcript.txt").write_text(raw_transcript, encoding="utf-8")
        LOG.info("DRY RUN: skipped email + state update; wrote /tmp/summary.md (Claude output) and /tmp/transcript.txt (raw whisper)")
        return 0

    send_email(summary, subject, gmail_from, gmail_password, recipients)

    # Only update state after a successful email send so failed runs are safe to retry.
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(episode["guid"] + "\n", encoding="utf-8")
    LOG.info("state updated: %s", episode["guid"])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
