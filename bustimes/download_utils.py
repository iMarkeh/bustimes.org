import datetime
import logging
import os

import requests
from django.utils.http import http_date, parse_http_date

session = requests.Session()


def write_file(path, response):
    with open(path, "wb") as open_file:
        for chunk in response.iter_content(chunk_size=102400):
            open_file.write(chunk)


def download(path, url):
    response = session.get(url, stream=True, timeout=60)
    assert response.ok
    write_file(path, response)


def download_if_changed(path, url, params=None):
    logger = logging.getLogger(__name__)

    headers = {"User-Agent": "bustimes.org"}
    modified = True
    if path.exists():
        headers["if-modified-since"] = http_date(os.path.getmtime(path))
        response = session.head(url, params=params, headers=headers, timeout=10)
        if response.status_code == 304:
            modified = False

    if modified:
        response = session.get(
            url, params=params, headers=headers, stream=True, timeout=10
        )

        if response.status_code == 304:
            modified = False
        elif not response.ok:
            modified = False
            logger.error(f"{response} {url}")
        else:
            write_file(path, response)

    last_modified = None
    if "x-amz-meta-cb-modifiedtime" in response.headers:
        last_modified = response.headers["x-amz-meta-cb-modifiedtime"]
    elif "last-modified" in response.headers:
        last_modified = response.headers["last-modified"]
    if last_modified:
        last_modified = datetime.datetime.fromtimestamp(
            parse_http_date(last_modified), datetime.timezone.utc
        )

    return modified, last_modified
