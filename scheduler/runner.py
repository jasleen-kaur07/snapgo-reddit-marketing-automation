# scheduler/runner.py
import re
import json
import uuid
import os
import glob
from datetime import datetime
import time
from reddit.scraper import scrape_subreddits
from db.writer import insert_post, update_post_filter_scores, update_post_insight, mark_insight_processed, mark_posts_in_history
from db.reader import get_top_insights_from_today, get_posts_by_ids, get_post_parent_mapping
from db.schema import create_tables
from gpt.filters import prepare_batch_payload as prepare_filter_batch, estimate_batch_cost as estimate_filter_cost
from gpt.insights import prepare_insight_batch, estimate_insight_cost
from gpt.batch_provider import (
    generate_batch_payload, submit_batch_job, poll_batch_status,
    download_batch_results, download_batch_results_if_available,
    get_processed_custom_ids, add_estimated_batch_cost,
    get_active_enqueued_tokens, probe_enqueued_capacity,
    retrieve_batch, extract_content_from_result,
    clean_storage
)
from db.cleaner import clean_old_entries
from scheduler.cost_tracker import initialize_cost_tracking, can_process_batch
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import ensure_directory_exists, sanitize_text

log = setup_logger()
config = get_config()

def submit_with_backoff(batch_items, model, generate_file_fn, label="filter") -> str | None:
    delay = 10
    max_retries = 20
    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"[Retry {attempt}/{max_retries}] Submitting {label} batch with {len(batch_items)} items...")
            file_path = generate_file_fn(batch_items, model)
            batch_id = submit_batch_job(file_path)
            batch_info = poll_batch_status(batch_id)
            status = batch_info["status"]

            if status == "completed":
                return batch_id
            elif status == "cancelled":
                log.warning(f"{label.capitalize()} batch {batch_id} was cancelled. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
                if delay > 3600:
                    delay = 3600  # cap delay to 1 hour
                continue
            elif status == "failed":
                log.warning(f"{label.capitalize()} batch failed. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
                if delay > 3600:
                    delay = 3600  # cap delay to 1 hour
                continue
        except Exception as e:
            log.error(f"Error in {label} batch retry #{attempt}: {str(e)}")
            time.sleep(delay)
            delay *= 2
            if delay > 3600:
                    delay = 3600  # cap delay to 1 hour

    # All retries failed
    log.error(f"❌ {label.capitalize()} batch failed after {max_retries} retries. Deferring.")
    save_failed_batch(batch_items, label)
    return None

def _estimate_batch_tokens(batch_items):
    """Sum the estimated tokens for a batch from item metadata."""
    return sum(item.get("meta", {}).get("estimated_tokens", 300) for item in batch_items)



_provider = config["ai"]["provider"]
_provider_config = config["ai"][_provider]
ENQUEUED_TOKEN_LIMITS = _provider_config.get("enqueued_token_limits", {})
DEFAULT_ENQUEUED_TOKEN_LIMIT = _provider_config.get("default_enqueued_token_limit", 5_000_000)


def _wait_for_batch_confirmation(batch_id, timeout=300, poll_interval=10):
    """Quick-poll a newly submitted batch until it leaves 'validating' state.

    Returns the confirmed status: 'in_progress', 'failed', 'cancelled', etc.
    If the batch is still validating after timeout, returns 'validating'.

    For Anthropic, batches go straight to 'in_progress' (processing_status),
    so this typically returns immediately.
    """
    provider = config["ai"]["provider"]
    start = time.time()
    while time.time() - start < timeout:
        try:
            batch = retrieve_batch(batch_id)
            if provider == "anthropic":
                status = batch.processing_status
                # Anthropic statuses: in_progress, ended
                if status == "ended":
                    return "completed"
                return "in_progress"
            else:
                status = batch.status
                if status != "validating":
                    return status
        except Exception as e:
            log.warning(f"Error checking batch {batch_id}: {e}")
        time.sleep(poll_interval)
    return "validating"


def submit_batches_parallel(all_sub_batches, model, generate_file_fn, label,
                            max_retries=5, enqueued_token_limit=None):
    """Submit batches with confirmed-capacity scheduling.

    Strategy: submit one batch at a time, wait for OpenAI to confirm it's
    actually processing (in_progress) before submitting the next. This avoids
    the "spray and pray" problem where 25 batches are submitted but 23 fail
    because OpenAI's internal enqueued token limit was exceeded.

    Multiple batches run in parallel — we just gate new submissions on
    confirmed capacity rather than blindly firing everything at once.

    Flow:
    1. Submit a batch.
    2. Quick-poll (every 10s) until it moves to in_progress or fails.
    3. If confirmed (in_progress): check if there's capacity for another batch.
    4. If failed with 0/0: capacity issue — back off, then retry.
    5. Poll all confirmed in-flight batches for completion.
    6. As batches complete and free capacity, submit more.
    7. Repeat until all batches are processed.
    """
    if enqueued_token_limit is None:
        enqueued_token_limit = ENQUEUED_TOKEN_LIMITS.get(model, DEFAULT_ENQUEUED_TOKEN_LIMIT)

    # Probe: verify enqueued capacity is actually free before starting.
    # This catches the OpenAI ghost-token bug where failed batches' tokens
    # are never released from the quota.
    if not probe_enqueued_capacity(model):
        log.error(f"Enqueued capacity for {model} is blocked (ghost tokens). "
                  f"Cannot proceed with {label} batch processing.")
        save_failed_batch(
            [item for batch in all_sub_batches for item in batch], label
        )
        return []

    result_paths = []
    confirmed = {}  # batch_id -> {"items": [...], "retries": int, "tokens": int}
    confirmed_tokens = 0  # tokens in confirmed in_progress/finalizing batches

    # Queue holds (items, retries) tuples
    submit_queue = [(batch_items, 0) for batch_items in all_sub_batches]
    backoff_delay = 0  # seconds to wait before next submit attempt

    log.info(f"Starting {label} batch processing: {len(submit_queue)} batches queued, "
             f"token limit: {enqueued_token_limit:,}")

    while submit_queue or confirmed:
        # --- Submit phase: submit one batch at a time, confirm before next ---
        while submit_queue and backoff_delay == 0:
            batch_items, retries = submit_queue[0]
            batch_tokens = _estimate_batch_tokens(batch_items)

            # Check capacity using confirmed tokens from OpenAI
            enqueued_tokens = get_active_enqueued_tokens()
            if enqueued_tokens > 0 and enqueued_tokens + batch_tokens > enqueued_token_limit:
                log.info(f"Token budget full ({enqueued_tokens:,}/{enqueued_token_limit:,}). "
                         f"Next batch needs {batch_tokens:,} tokens — waiting for capacity.")
                break

            # Submit the batch
            try:
                add_estimated_batch_cost(batch_items, model)
                file_path = generate_file_fn(batch_items, model)
                batch_id = submit_batch_job(file_path, estimated_tokens=batch_tokens)
                log.info(f"Submitted {label} batch {batch_id} with {len(batch_items)} items "
                         f"({batch_tokens:,} tokens). Waiting for confirmation...")
            except Exception as e:
                log.error(f"Failed to submit {label} batch: {e}. Deferring {len(batch_items)} items.")
                save_failed_batch(batch_items, label)
                submit_queue.pop(0)
                continue

            submit_queue.pop(0)

            # Wait for OpenAI to confirm (validating -> in_progress or failed)
            status = _wait_for_batch_confirmation(batch_id)

            if status in ("in_progress", "finalizing", "completed"):
                log.info(f"Batch {batch_id} confirmed: {status}")
                confirmed[batch_id] = {"items": batch_items, "retries": retries, "tokens": batch_tokens}
                confirmed_tokens += batch_tokens
                backoff_delay = 0  # reset backoff on success

                # If completed already during confirmation, handle it immediately
                if status == "completed":
                    path = f"data/batch_responses/{label}_result_{uuid.uuid4().hex}.jsonl"
                    try:
                        download_batch_results(batch_id, path)
                        result_paths.append(path)
                        processed_ids = get_processed_custom_ids(path)
                        unprocessed = [i for i in batch_items if i["id"] not in processed_ids]
                        if unprocessed and retries < max_retries:
                            log.warning(f"Retrying {len(unprocessed)} non-succeeded items from completed batch {batch_id}")
                            submit_queue.append((unprocessed, retries + 1))
                        elif unprocessed:
                            log.warning(f"Max retries reached for {len(unprocessed)} items from batch {batch_id}")
                            save_failed_batch(unprocessed, label)
                    except Exception as e:
                        log.error(f"Failed to download results for batch {batch_id}: {e}")
                    confirmed_tokens -= batch_tokens
                    del confirmed[batch_id]
            elif status == "failed":
                # 0/0 failure = likely capacity/ghost-token issue.
                # Probe to wait until capacity is actually free before retrying.
                if retries < max_retries:
                    log.warning(f"Batch {batch_id} failed (likely capacity). "
                                f"Probing to wait for capacity before retry "
                                f"({retries + 1}/{max_retries})...")
                    if probe_enqueued_capacity(model, max_wait=3600):
                        submit_queue.insert(0, (batch_items, retries + 1))
                    else:
                        log.error(f"Capacity still blocked after probing. Deferring batch.")
                        save_failed_batch(batch_items, label)
                else:
                    # All retries exhausted but probes succeed — the batch is
                    # too large for OpenAI to accept.  Split it in half and
                    # re-queue both halves with fresh retry counters.
                    if len(batch_items) > 1:
                        mid = len(batch_items) // 2
                        half_a, half_b = batch_items[:mid], batch_items[mid:]
                        log.warning(
                            f"Batch {batch_id} failed after {max_retries} retries "
                            f"({len(batch_items)} items). Splitting into 2 halves "
                            f"({len(half_a)} + {len(half_b)}) and re-queuing.")
                        submit_queue.insert(0, (half_b, 0))
                        submit_queue.insert(0, (half_a, 0))
                    else:
                        log.error(f"Batch {batch_id} failed after {max_retries} retries "
                                  f"(single item — cannot split). Deferring.")
                        save_failed_batch(batch_items, label)
                break  # exit submit loop to wait/re-check
            elif status == "validating":
                # Still validating after timeout — treat as tentatively confirmed
                log.warning(f"Batch {batch_id} still validating after timeout. "
                            f"Tracking it and continuing.")
                confirmed[batch_id] = {"items": batch_items, "retries": retries, "tokens": batch_tokens}
                confirmed_tokens += batch_tokens
            else:
                # cancelled or other unexpected status
                if retries < max_retries:
                    log.warning(f"Batch {batch_id} status: {status}. Re-queuing (retry {retries + 1}/{max_retries})...")
                    submit_queue.insert(0, (batch_items, retries + 1))
                else:
                    log.error(f"Batch {batch_id} {status} after {max_retries} retries. Deferring.")
                    save_failed_batch(batch_items, label)

        # --- Poll phase: check all confirmed in-flight batches ---
        for batch_id, info in list(confirmed.items()):
            try:
                batch = retrieve_batch(batch_id)
            except Exception as e:
                log.error(f"Error retrieving batch {batch_id}: {e}")
                continue

            provider = config["ai"]["provider"]
            if provider == "anthropic":
                counts = batch.request_counts
                completed_count = counts.succeeded + counts.errored
                total_count = completed_count + counts.processing + counts.canceled + counts.expired
                status = "completed" if batch.processing_status == "ended" else batch.processing_status
                if status == "in_progress":
                    status = "in_progress"  # keep as-is for the logic below
            else:
                status = batch.status
                request_counts = batch.request_counts
                completed_count = getattr(request_counts, "completed", 0)
                total_count = getattr(request_counts, "total", 0)
            log.info(f"Batch {batch_id} status: {status} — {completed_count}/{total_count} completed")

            if status == "completed":
                path = f"data/batch_responses/{label}_result_{uuid.uuid4().hex}.jsonl"
                try:
                    download_batch_results(batch_id, path)
                    result_paths.append(path)
                    processed_ids = get_processed_custom_ids(path)
                    unprocessed = [i for i in info["items"] if i["id"] not in processed_ids]
                    if unprocessed and info["retries"] < max_retries:
                        log.warning(f"Retrying {len(unprocessed)} non-succeeded items from completed batch {batch_id}")
                        submit_queue.append((unprocessed, info["retries"] + 1))
                    elif unprocessed:
                        log.warning(f"Max retries reached for {len(unprocessed)} items from batch {batch_id}")
                        save_failed_batch(unprocessed, label)
                except Exception as e:
                    log.error(f"Failed to download results for batch {batch_id}: {e}")
                confirmed_tokens -= info["tokens"]
                del confirmed[batch_id]

            elif status == "expired":
                path = f"data/batch_responses/{label}_result_{uuid.uuid4().hex}.jsonl"
                if download_batch_results_if_available(batch_id, path):
                    result_paths.append(path)
                    processed_ids = get_processed_custom_ids(path)
                    unprocessed = [i for i in info["items"] if i["id"] not in processed_ids]
                    if unprocessed and info["retries"] < max_retries:
                        log.info(f"Retrying {len(unprocessed)} unprocessed items from expired batch {batch_id}")
                        submit_queue.append((unprocessed, info["retries"] + 1))
                    elif unprocessed:
                        log.warning(f"Max retries reached for {len(unprocessed)} items from batch {batch_id}")
                        save_failed_batch(unprocessed, label)
                else:
                    if info["retries"] < max_retries:
                        log.info(f"No partial results for expired batch {batch_id}. Re-queuing entire batch.")
                        submit_queue.append((info["items"], info["retries"] + 1))
                    else:
                        log.warning(f"Max retries reached for batch {batch_id}. Deferring.")
                        save_failed_batch(info["items"], label)
                confirmed_tokens -= info["tokens"]
                del confirmed[batch_id]

            elif status in ("failed", "cancelled"):
                if info["retries"] < max_retries:
                    log.warning(f"{label.capitalize()} batch {batch_id} {status}. "
                                f"Re-queuing for retry ({info['retries'] + 1}/{max_retries})...")
                    submit_queue.append((info["items"], info["retries"] + 1))
                else:
                    log.error(f"{label.capitalize()} batch {batch_id} {status} after {max_retries} retries. Deferring.")
                    save_failed_batch(info["items"], label)
                confirmed_tokens -= info["tokens"]
                del confirmed[batch_id]

            # else: still in_progress/finalizing — keep polling

        # --- Wait phase ---
        if submit_queue or confirmed:
            if backoff_delay > 0:
                log.info(f"Backing off for {backoff_delay}s before next submit attempt. "
                         f"Queue: {len(submit_queue)} batches, In-flight: {len(confirmed)} batches")
                time.sleep(backoff_delay)
                backoff_delay = 0  # reset after waiting
            else:
                remaining = len(submit_queue)
                in_flight = len(confirmed)
                log.info(f"Waiting 60s. Queue: {remaining} batches, "
                         f"In-flight: {in_flight} batches, "
                         f"Confirmed tokens: {confirmed_tokens:,}/{enqueued_token_limit:,}")
                time.sleep(60)

    log.info(f"{label.capitalize()} batch processing complete. "
             f"Downloaded {len(result_paths)} result files.")
    return result_paths


def save_failed_batch(batch_items, label, folder="data/deferred"):
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, f"failed_{label}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for item in batch_items:
            f.write(json.dumps(item) + "\n")
    log.warning(f"Deferred {len(batch_items)} {label} items to {out_path}")

def is_valid_post(post):
    """Ensure post has valid title and body after sanitization."""
    title = sanitize_text(post.get("title", ""))
    body = sanitize_text(post.get("body", ""))
    return bool(title and body)

def split_batch_by_token_limit(payload, model: str, token_limit: int = 200_000):
    batches = []
    current_batch = []
    current_tokens = 0

    for item in payload:
        tokens = item.get("meta", {}).get("estimated_tokens", 300)
        if current_tokens + tokens > token_limit:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += tokens

    if current_batch:
        batches.append(current_batch)

    return batches

def clean_old_batch_files(folder="data/batch_responses", days_old=None):
    """Delete .jsonl files older than `days_old`. Defaults to config value."""
    days_old = days_old or config.get("cleanup", {}).get("batch_response_retention_days", 3)
    cutoff = time.time() - (days_old * 86400)

    deleted = 0
    for fname in os.listdir(folder):
        path = os.path.join(folder, fname)
        if fname.endswith(".jsonl") and os.path.isfile(path):
            if os.path.getmtime(path) < cutoff:
                try:
                    os.remove(path)
                    deleted += 1
                except Exception as e:
                    log.warning(f"Failed to delete old file {path}: {e}")
    log.info(f"Cleaned up {deleted} old batch response files older than {days_old} days.")

def get_high_potential_ids_from_filter_results(result_paths=None, score_threshold=7.0):
    processed = 0
    high_candidates = {}  # post_id -> weighted_score (before dedup)
    all_processed_ids = set()
    weights = config["scoring"]
    if result_paths is None:
        result_paths = glob.glob("data/batch_responses/filter_result_*.jsonl")
    for path in result_paths:
        with open(path, "r") as f:
            for line in f:
                try:
                    result = json.loads(line)
                    if result.get("result_type") and result.get("result_type") != "succeeded":
                        continue
                    processed += 1
                    post_id, content = extract_content_from_result(result)
                    scores = json.loads(content)
                    technical_depth = scores.get("technical_depth_score", 5)
                    min_depth = weights.get("min_technical_depth", 4)

                    weighted_score = (
                        scores["relevance_score"] * weights["relevance_weight"] +
                        scores["emotional_intensity"] * weights["emotion_weight"] +
                        scores["pain_point_clarity"] * weights["pain_point_weight"] +
                        scores.get("implementability_score", 5) * weights.get("implementability_weight", 0) +
                        technical_depth * weights.get("technical_depth_weight", 0.2)
                    )
                    update_post_filter_scores(post_id, scores)
                    all_processed_ids.add(post_id)
                    # Hard filter: reject vibe-codeable ideas with low technical depth
                    if technical_depth < min_depth:
                        log.debug(f"Rejected post {post_id}: technical_depth_score {technical_depth} < {min_depth}")
                        continue
                    if weighted_score >= score_threshold:
                        high_candidates[post_id] = weighted_score
                except Exception as e:
                    log.error(f"Error parsing filter result line: {e}")

    # Deduplicate: keep only the highest-scoring entry per thread
    parent_mapping = get_post_parent_mapping(set(high_candidates.keys()))
    thread_best = {}  # thread_id -> (post_id, weighted_score)
    for post_id, score in high_candidates.items():
        thread_id = parent_mapping.get(post_id) or post_id  # comments group under parent, posts are their own thread
        if thread_id not in thread_best or score > thread_best[thread_id][1]:
            thread_best[thread_id] = (post_id, score)

    high_ids = {post_id for post_id, _ in thread_best.values()}
    deduped_count = len(high_candidates) - len(high_ids)
    if deduped_count > 0:
        log.info(f"Deduplicated {deduped_count} same-thread entries (kept best per thread)")

    log.info(f"Processed {processed} filter results, found {len(high_ids)} high-potential posts (from {len(high_candidates)} candidates)")
    return high_ids, all_processed_ids

def is_ai_configured() -> bool:
    provider = config["ai"].get("provider")
    if not provider:
        return False
    provider_cfg = config["ai"].get(provider)
    if not provider_cfg:
        return False
    api_key = provider_cfg.get("api_key")
    if not api_key:
        return False
    if "your_" in api_key or "placeholder" in api_key or api_key.strip() == "":
        return False
    return True

def detect_location(title: str, body: str, subreddit: str) -> dict:
    text = (title + " " + body).lower()
    sub = subreddit.lower()
    
    ncr_locations = {
        "new delhi": "Delhi",
        "delhi": "Delhi",
        "noida": "Noida",
        "greater noida": "Greater Noida",
        "gurugram": "Gurugram",
        "gurgaon": "Gurugram",
        "ghaziabad": "Ghaziabad",
        "faridabad": "Faridabad",
        "sonipat": "Sonipat",
        "bahadurgarh": "Bahadurgarh",
        "jewar": "Jewar",
        "yamuna expressway": "Yamuna Expressway"
    }
    
    other_cities = {
        "bangalore": "Bangalore",
        "bengaluru": "Bangalore",
        "mumbai": "Mumbai",
        "bombay": "Mumbai",
        "hyderabad": "Hyderabad",
        "pune": "Pune"
    }
    
    city = ""
    state = ""
    country = ""
    
    # First priority: Explicit NCR locations in text
    for key, name in ncr_locations.items():
        if key in text:
            city = name
            state = "Delhi NCR"
            country = "India"
            break
            
    # Second priority: Subreddit matches NCR
    if not city:
        if sub in ncr_locations:
            city = ncr_locations[sub]
            state = "Delhi NCR"
            country = "India"
            
    # Third priority: Other Indian cities in text
    if not city:
        for key, name in other_cities.items():
            if key in text:
                city = name
                if key in ("bangalore", "bengaluru"):
                    state = "Karnataka"
                elif key in ("mumbai", "bombay", "pune"):
                    state = "Maharashtra"
                elif key in ("hyderabad",):
                    state = "Telangana"
                country = "India"
                break
                
    # Fourth priority: Subreddit matches other cities
    if not city:
        if sub in other_cities:
            city = other_cities[sub]
            if sub in ("bangalore", "bengaluru"):
                state = "Karnataka"
            elif sub in ("mumbai", "pune"):
                state = "Maharashtra"
            elif sub in ("hyderabad",):
                state = "Telangana"
            country = "India"
            
    # Default to India if NCR/other cities or India subreddits
    if not country:
        if sub in ("india", "indiasocial", "delhi", "noida", "gurgaon", "gurugram", "bangalore", "mumbai", "hyderabad", "pune") or "india" in text or "rs." in text or "rupees" in text:
            country = "India"
            
    # Fallback to general NCR state if NCR city is matched
    if city in ncr_locations.values() and not state:
        state = "Delhi NCR"
        country = "India"
        
    # Simple parse for origin/destination
    origin = ""
    destination = ""
    route_match = re.search(r"from\s+([a-zA-Z0-9\s_]{3,20})\s+to\s+([a-zA-Z0-9\s_]{3,20})", text)
    if route_match:
        origin = route_match.group(1).strip().title()
        destination = route_match.group(2).strip().title()
        
    return {
        "country": country,
        "state": state,
        "city": city,
        "origin": origin,
        "destination": destination
    }

def classify_campaign_and_intent(title: str, body: str) -> tuple[str, str, str]:
    text = (title + " " + body).lower()
    
    campaigns = {
        "Student Commute": ["student", "college", "university", "hostel", "campus", "school", "class", "affordable"],
        "Office Commute": ["office", "work", "corporate", "tech park", "employee", "hybrid", "daily travel"],
        "Carpool Promotion": ["carpool", "ride sharing", "share", "sharing", "pool", "pooling", "bike pooling"],
        "Fuel Savings": ["fuel", "petrol", "diesel", "price", "expensive", "expenses", "saving", "cost", "fare"],
        "Traffic & Congestion": ["traffic", "parking", "jam", "gridlock", "slow", "late", "delay"],
        "Public Transport": ["metro", "bus", "train", "ticket", "station", "rail"]
    }
    
    campaign_scores = {c: 0 for c in campaigns}
    for campaign, kws in campaigns.items():
        for kw in kws:
            if kw in text:
                campaign_scores[campaign] += 1
                
    best_campaign = max(campaign_scores, key=campaign_scores.get)
    if campaign_scores[best_campaign] == 0:
        best_campaign = "General Transportation"
        
    intent = f"Discussing transit challenges related to {best_campaign.lower()}"
    
    responses = {
        "Student Commute": "Travelling to college daily can be super exhausting and expensive. You should check out Snapgo—it's a ride-sharing/carpooling app designed for students and daily commuters. It lets you find other students going to the same campus to share rides and split travel costs easily. Hope this helps save some pocket money!",
        "Office Commute": "Daily office travel in this rush hour is really draining. If you want a more comfortable and budget-friendly commute, you might want to try Snapgo. It connects verified corporate professionals sharing daily office routes, letting you split fuel/cab costs and network during the ride. Definitely beats driving in traffic or fighting for metro seats!",
        "Carpool Promotion": "If you are looking for ride-sharing options, check out Snapgo. It's a platform built specifically for daily commuters in Delhi NCR to find verified professionals to carpool with. It helps share fuel expenses, reduces traffic congestion, and makes the daily commute much more social and comfortable.",
        "Fuel Savings": "Fuel costs and rising cab fares are getting out of hand. A great way to save is by ride sharing. You should try Snapgo—it's a carpooling app that helps daily commuters connect and share rides along similar routes to split fuel costs. It can easily cut your monthly travel budget in half!",
        "Traffic & Congestion": "Driving in this peak traffic is incredibly frustrating. You should try checking out Snapgo. By connecting you with other commuters on your route, it makes carpooling simple so we can get more cars off the road and split fuel costs. It's a great way to escape the stress of daily driving!",
        "Public Transport": "Metro queues and bus crowds during rush hour can be tough. If you're looking for a direct, comfortable alternative without spending a fortune on private cabs, try looking for carpools on Snapgo. It matches you with professionals sharing the same route so you can travel comfortably and share expenses.",
        "General Transportation": "Daily commuting can be quite a challenge. If you are looking for convenient, budget-friendly travel options, you might want to check out Snapgo. It is a smart ride-sharing app that connects commuters going along the same route to split fuel costs and carpool."
    }
    
    suggested_response = responses.get(best_campaign, responses["General Transportation"])
    return best_campaign, intent, suggested_response

def run_local_fallback_pipeline(posts: list[dict]):
    log.info(f"Processing {len(posts)} posts locally...")
    
    transit_keywords = config["scraper"].get("keywords", [])
    if not transit_keywords:
        transit_keywords = [
            "carpool", "commute", "ride sharing", "metro", "bus", "train",
            "fuel cost", "office travel", "student travel", "traffic", "parking"
        ]
        
    for post in posts:
        post_id = post["id"]
        title = post.get("title", "")
        body = post.get("body", "")
        subreddit = post.get("subreddit", "")
        text = (title + " " + body).lower()
        
        # 1. Relevance Score
        matching_kws = [kw for kw in transit_keywords if kw.lower() in text]
        relevance = min(10.0, 5.0 + float(len(matching_kws)) * 1.0)
        
        # 2. Pain and Intent Strength
        pain_kws = ["exhausted", "late", "stuck", "frustrated", "nightmare", "horrible", "awful", "expensive", "costly", "spend", "hell", "bad"]
        has_pain = any(kw in text for kw in pain_kws)
        pain_severity = 8.0 if has_pain else 5.0
        emotion_score = 8.0 if has_pain else 5.0
        
        intent_kws = ["looking for", "find", "suggest", "share", "want to", "need to", "how to", "any option"]
        has_intent = any(kw in text for kw in intent_kws)
        intent_strength = 8.0 if has_intent else 5.0
        
        implementability = 6.0
        tech_depth = 5.0
        
        scores_dict = {
            "relevance_score": relevance,
            "emotional_intensity": emotion_score,
            "pain_point_clarity": pain_severity,
            "implementability_score": implementability,
            "technical_depth_score": tech_depth,
            "intent_strength": intent_strength,
            "pain_severity": pain_severity
        }
        update_post_filter_scores(post_id, scores_dict)
        
        # 3. Location Detection
        geo = detect_location(title, body, subreddit)
        
        # 4. Campaign & Suggested Response Classification
        campaign, intent, response = classify_campaign_and_intent(title, body)
        
        # 5. Priority Score Calculation
        score, level = calculate_priority_score(post, relevance, intent_strength, pain_severity, geo)
        
        # 6. Save Insight and mark processed
        tags_list = ["transit", campaign.lower().replace(' ', '-')]
        insight = {
            "user_intent": intent,
            "marketing_campaign": campaign,
            "country": geo["country"],
            "state": geo["state"],
            "city": geo["city"],
            "origin": geo["origin"],
            "destination": geo["destination"],
            "suggested_response": response,
            "overall_priority_score": score,
            "priority_level": level,
            "roi_weight": int(score / 10),
            "tags": tags_list
        }
        
        update_post_insight(post_id, insight)
        mark_insight_processed(post_id)
        
    post_ids = [p["id"] for p in posts]
    mark_posts_in_history(post_ids)
    log.info(f"Successfully processed {len(posts)} posts locally and stored in database.")

def run_daily_pipeline():
    log.info("\U0001F680 Starting Reddit scraping and analysis pipeline")

    ensure_directory_exists("data/deferred")
    ensure_directory_exists("data")
    ensure_directory_exists("data/batch_responses")
    clean_old_batch_files()
    clean_storage()
    create_tables()
    initialize_cost_tracking()

    log.info("Step 1: Cleaning old database entries...")
    clean_old_entries()

    log.info("Step 2: Scraping Reddit posts...")
    scraped_posts = scrape_subreddits()
    if not scraped_posts:
        log.warning("No posts found to analyze. Exiting pipeline.")
        return

    log.info(f"Found {len(scraped_posts)} posts before filtering invalid entries...")
    scraped_posts = [p for p in scraped_posts if is_valid_post(p)]
    log.info(f"{len(scraped_posts)} posts remain after sanitization/validation.")

    if not scraped_posts:
        log.warning("No valid posts after sanitization. Exiting pipeline.")
        return

    if not is_ai_configured():
        log.warning("⚠️ OpenAI/Anthropic API key is not configured in .env file.")
        log.info("Running local fallback processing pipeline...")
        run_local_fallback_pipeline(scraped_posts)
        log.info("✅ Pipeline completed successfully via local fallback.")
        return

    log.info("Step 3: Preparing posts for filtering...")
    filter_batch = prepare_filter_batch(scraped_posts)
    filter_cost = estimate_filter_cost(scraped_posts)
    log.info(f"Estimated cost for filtering: ${filter_cost:.2f}")

    if not can_process_batch(filter_cost):
        log.error("Insufficient budget for filtering. Exiting pipeline.")
        return

    model_filter = config["ai"][config["ai"]["provider"]]["model_filter"]
    filter_batches = split_batch_by_token_limit(filter_batch, model_filter)

    filter_result_paths = submit_batches_parallel(filter_batches, model_filter, generate_batch_payload, "filter")

    log.info("Step 4: Selecting high-potential posts from filter results...")
    high_potential_ids, all_filtered_ids = get_high_potential_ids_from_filter_results(filter_result_paths)

    # Mark posts that were filtered but NOT high-potential into history
    # (they're fully done — scored but below threshold, no further processing needed)
    below_threshold_ids = all_filtered_ids - high_potential_ids
    if below_threshold_ids:
        mark_posts_in_history(list(below_threshold_ids))
        log.info(f"Marked {len(below_threshold_ids)} below-threshold posts in history.")

    if not high_potential_ids:
        log.info("No high-value posts found. Exiting pipeline.")
        return

    deep_posts = get_posts_by_ids(high_potential_ids, require_unprocessed=True)
    if not deep_posts:
        log.info("No new posts left for deep insight. Exiting pipeline.")
        return

    insight_batch = prepare_insight_batch(deep_posts)
    insight_cost = estimate_insight_cost(insight_batch)
    log.info(f"Estimated cost for insight analysis: ${insight_cost:.2f}")

    if not can_process_batch(insight_cost):
        log.error("Insufficient budget for insight analysis. Exiting pipeline.")
        return

    log.info(f"Submitting batch of {len(insight_batch)} posts for deep analysis...")
    log.info(f"Preparing {len(insight_batch)} posts for deep insight...")
    model_deep = config["ai"][config["ai"]["provider"]]["model_deep"]
    insight_batches = split_batch_by_token_limit(insight_batch, model_deep)
    all_insight_paths = submit_batches_parallel(
        insight_batches, model_deep, generate_batch_payload, "insight"
    )

    log.info("Step 5: Updating posts with deep insights...")
    insight_completed_ids = []
    try:
        for insight_path in all_insight_paths:
            with open(insight_path, "r", encoding="utf-8") as f:
                for line in f:
                    result = json.loads(line)
                    post_id, content = extract_content_from_result(result)
                    try:
                        insight = json.loads(content)
                        
                        # Retrieve post and filter scores to calculate priority
                        post_records = get_posts_by_ids({post_id})
                        if post_records:
                            post_rec = post_records[0]
                            rel = post_rec.get("relevance_score") or 5.0
                            intent = post_rec.get("intent_strength") or 5.0
                            pain = post_rec.get("pain_severity") or 5.0
                            
                            score, level = calculate_priority_score(post_rec, rel, intent, pain, insight)
                            insight["overall_priority_score"] = score
                            insight["priority_level"] = level
                            insight["roi_weight"] = int(score / 10)
                        
                        update_post_insight(post_id, insight)
                        mark_insight_processed(post_id)
                        insight_completed_ids.append(post_id)
                    except Exception as e:
                        log.error(f"Error parsing insight for post {post_id}: {str(e)}")
    except Exception as e:
        log.error(f"Error reading insight results: {str(e)}")

    # Mark posts that completed insight analysis into history
    if insight_completed_ids:
        mark_posts_in_history(insight_completed_ids)
        log.info(f"Marked {len(insight_completed_ids)} insight-completed posts in history.")

    output_limit = config["scoring"].get("output_top_n", 10)
    top_posts = get_top_insights_from_today(limit=output_limit)
    log.info(f"✅ Pipeline finished. Found {len(top_posts)} qualified leads.")

    for i, post in enumerate(top_posts[:5], 1):
        log.info(f"{i}. [{post['subreddit']}] {post['title']} — Priority Score: {post.get('overall_priority_score', 0)} | Level: {post.get('priority_level', 'Low')} - {post['url']}")


def calculate_priority_score(post: dict, relevance: float, intent_strength: float, pain_severity: float, insight_geo: dict) -> tuple[float, str]:
    # 1. Transportation Relevance (max 25)
    rel_pts = relevance * 2.5
    
    # 2. Intent Strength (max 15)
    intent_pts = intent_strength * 1.5
    
    # 3. Pain Severity (max 15)
    pain_pts = pain_severity * 1.5
    
    # 4. Location Match (max 30)
    country = (insight_geo.get("country") or "").lower()
    state = (insight_geo.get("state") or "").lower()
    city = (insight_geo.get("city") or "").lower()
    
    ncr_locations = {
        "delhi", "new delhi", "noida", "greater noida", "gurgaon", 
        "gurugram", "ghaziabad", "faridabad", "sonipat", "bahadurgarh", 
        "jewar", "yamuna expressway"
    }
    
    is_ncr = (
        city in ncr_locations or 
        state in ncr_locations or 
        any(ncr in (post.get("title") or "").lower() or ncr in (post.get("body") or "").lower() for ncr in ncr_locations)
    )
    is_india = (
        country == "india" or 
        state == "india" or 
        any(sub in (post.get("subreddit") or "").lower() for sub in ["india", "indiasocial", "delhi", "noida", "gurgaon", "gurugram", "bangalore", "mumbai", "hyderabad", "pune"])
    )
    
    if is_ncr:
        loc_pts = 30.0
    elif is_india:
        loc_pts = 15.0
    else:
        loc_pts = 0.0
        
    # 5. Freshness (max 10)
    created_utc = post.get("created_utc") or time.time()
    age_days = (time.time() - created_utc) / 86400
    fresh_pts = max(0.0, 10.0 - (age_days * 0.33))
    
    # 6. Engagement (max 5)
    engagement_pts = 3.0
    
    total = rel_pts + intent_pts + pain_pts + loc_pts + fresh_pts + engagement_pts
    total = min(100.0, max(0.0, total))
    
    if total >= 75:
        level = "Highest"
    elif total >= 50:
        level = "Medium"
    elif total >= 25:
        level = "Low"
    else:
        level = "Very Low"
        
    return total, level


if __name__ == "__main__":
    run_daily_pipeline()
