import logging
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("random-user")

def main():
    resp = requests.get("https://randomuser.me/api/", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if not results:
        log.warning("No results from randomuser")
        return
    person = results[0]
    first = person.get("name", {}).get("first", "<unknown>")
    last = person.get("name", {}).get("last", "<unknown>")
    log.info("Random user: %s %s", first, last)
    # return for downstream use if needed
    return {"first": first, "last": last}

if __name__ == "__main__":
    main()