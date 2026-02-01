from pathlib import Path
import re
import sys
import json

try:
    import requests
    from lxml import etree
except ModuleNotFoundError:
    print(
        "You need to install the following modules 'requests', 'lxml'.", file=sys.stderr
    )
    sys.exit(1)

try:
    from py_common import log
    from py_common.util import scraper_args
    from py_common.types import (
        ScrapedPerformer,
        ScrapedScene,
        ScrapedStudio,
        ScrapedTag,
    )
except ModuleNotFoundError:
    print(
        "You need to download the folder 'py_common' from the community repo! (CommunityScrapers/tree/master/scrapers/py_common)",
        file=sys.stderr,
    )
    sys.exit(1)

BASE_QUERY_URL = "https://fc2ppvdb.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0.1 Safari/605.1.15"
URL_SEARCH_PATTERN = r".+/articles/(\d{5,}).*"
CODE_SEARCH_PATTERN = r".*?(\d{5,}).*"

scraper = requests.Session()


def get_cookie_path():
    path = Path(__file__).parent / ("cookie")
    return path

def read_cookie() -> bool:
    session_path = get_cookie_path()
    try:
        with open(session_path, mode="r", encoding="utf8") as f:
            cookie = f.read()

        if not cookie:
            return False

        log.debug(f"Using cookie: {cookie}")
        scraper.cookies.set("fc2ppvdb_session", cookie)
        return True
    except OSError:
        return False


def write_cookie():
    try:
        cookie = scraper.cookies.get_dict().get("fc2ppvdb_session")
    except:
        log.warning("Writing empty cookie file")
        cookie = ""

    session_path = get_cookie_path()
    try:
        with open(session_path, mode="w", encoding="utf8") as f:
            f.write(cookie)
        log.debug(f"Write new cookie to file: {cookie}")
    except OSError as err:
        log.error(f"Failed to write cookie to file, err: {err}")


def extract_id(fragment: dict) -> str:
    if url := fragment.get("url"):
        search = re.search(pattern=URL_SEARCH_PATTERN, string=url)
        if search:
            return search[1]

    if code := fragment.get("code"):
        search = re.search(pattern=CODE_SEARCH_PATTERN, string=code)
        if search:
            return search[1]

    if title := fragment.get("title"):
        search = re.search(pattern=CODE_SEARCH_PATTERN, string=title)
        if search:
            return search[1]

    for file in fragment.get("files", []):
        search = re.search(pattern=CODE_SEARCH_PATTERN, string=file["path"])
        if search:
            return search[1]

    return None


def export_scene(result: dict) -> ScrapedScene:
    article = result["article"]

    tags = []
    for article_tag in article["tags"]:
        tag = ScrapedTag(name=article_tag["name"])
        tags.append(tag)

    performers = []
    for article_performer in article["actresses"]:
        performer = ScrapedPerformer(
            name=article_performer["name"],
            urls=[f"{BASE_QUERY_URL}/actresses/{article_performer["id"]}"],
        )
        performers.append(performer)

    image_url = article["image_url"]
    if not image_url.startswith("https"):
        image_url = f"{BASE_QUERY_URL}{image_url}"

    scene = ScrapedScene(
        title=article["title"],
        date=article["release_date"],
        tags=tags,
        performers=performers,
        studio=ScrapedStudio(
            name=article["writer"]["name"],
            url=f"{BASE_QUERY_URL}/writers/{article["writer"]["slug"]}",
        ),
        director=article["writer"]["name"],
        code=f"FC2-PPV-{article["video_id"]}",
        image=image_url,
        url=f"{BASE_QUERY_URL}/articles/{article["video_id"]}",
    )

    return scene


def request_article(video_id: str) -> requests.Response:
    article_url = f"{BASE_QUERY_URL}/articles/{video_id}"

    try:
        response = scraper.get(article_url, timeout=10, verify=False)
    except requests.RequestException as req_error:
        log.error(f"Requests article failed: {req_error}")
        return None

    return response


def request_article_info(video_id: str, csrf: str) -> requests.Response:
    try:
        xsrf = scraper.cookies.get_dict().get("XSRF-TOKEN")
    except:
        log.error("XSRF not found")
        return None

    scraper.headers.update(
        {
            "X-CSRF-TOKEN": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": xsrf,
        }
    )

    api_url = f"{BASE_QUERY_URL}/articles/article-info?videoid={video_id}"

    try:
        response = scraper.get(api_url, timeout=10, verify=False)
    except requests.RequestException as req_error:
        log.error(f"Request API failed: {req_error}")
        return None

    return response


def get_csrf(article_response: requests.Response) -> str:
    article_tree = etree.HTML(text=article_response.text)
    try:
        csrf = article_tree.xpath("//meta[@name='csrf-token']/@content")[0]
    except IndexError:
        log.error("CSRF not found")
        return None

    return csrf


def send_request(video_id: str) -> ScrapedScene:
    if not read_cookie():
        log.error("Please configure your session cookie in file fc2ppvdb/session")
        write_cookie()
        sys.exit(1)

    requests.packages.urllib3.disable_warnings()
    scraper.headers.update({"User-Agent": USER_AGENT})

    page_response = request_article(video_id)
    if page_response is None:
        log.error("Failed to request article page")
        write_cookie()
        sys.exit(1)

    csrf = get_csrf(page_response)
    if csrf is None:
        log.error("Failed to get CSRF token")
        write_cookie()
        sys.exit(1)

    article_response = request_article_info(video_id, csrf)
    if article_response is None:
        log.error("Failed to request article info")
        write_cookie()
        sys.exit(1)

    log.debug(f"Response: {article_response.text}")

    try:
        result = article_response.json()
    except json.decoder.JSONDecodeError as json_error:
        log.error(f"Failed to decode article info, reason: {json_error}")
        write_cookie()
        sys.exit(1)

    log.debug(f"Receive object: {result}")

    try:
        scene = export_scene(result)
    except KeyError as key_error:
        log.error(f"Failed to export article info, reason: {key_error} cannot be found")
        write_cookie()
        sys.exit(1)
    
    log.debug(f"Request of {video_id} finishes without issue")

    write_cookie()
    return scene


if __name__ == "__main__":
    op, args = scraper_args()

    match op, args:
        case "scene-by-fragment" | "scene-by-url", args:
            video_id = extract_id(args)
        case _:
            log.error(f"Operation: {op}, arguments: {json.dumps(args)}")
            sys.exit(1)

    if not video_id:
        log.error("Failed to extract id from input")
        sys.exit(1)

    result = send_request(video_id)
    output = json.dumps(result)
    print(output)
