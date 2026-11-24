"""Read JSON, HTML-table, and text responses from HTTP API endpoints."""

import hashlib
import ipaddress
import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from bs4 import BeautifulSoup


_RECORD_KEYS = ("data", "records", "results", "items")
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000
MAX_URLS = 5


def _json_records(payload):
    if isinstance(payload, list):
        return [
            item if isinstance(item, dict) else {"value": item}
            for item in payload
        ]
    if isinstance(payload, dict):
        for key in _RECORD_KEYS:
            values = payload.get(key)
            if isinstance(values, list):
                metadata = {
                    name: value
                    for name, value in payload.items()
                    if name != key
                }
                return [
                    (
                        {"record": item, "response_metadata": metadata}
                        if metadata
                        else item if isinstance(item, dict)
                        else {"value": item}
                    )
                    for item in values
                ]
        return [payload]
    return [{"value": payload}]


def _html_table_records(soup):
    records = []
    for table_index, table in enumerate(soup.find_all("table")):
        if table.find("table") or any(
            cell.get("colspan", "1") != "1" or cell.get("rowspan", "1") != "1"
            for cell in table.find_all(["th", "td"])
        ):
            raise ValueError("Nested tables and merged HTML cells require a reviewed mapping")
        rows = []
        for row_index, row in enumerate(table.find_all("tr"), 1):
            cells = row.find_all(["th", "td"])
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if values and any(values):
                rows.append((values, any(cell.name == "th" for cell in cells), row_index))
        if not rows:
            continue

        headers, has_header, _ = rows[0]
        if has_header:
            data_rows = rows[1:]
            if not all(headers) or len({h.casefold() for h in headers}) != len(headers):
                raise ValueError("Blank or duplicate HTML headers require a reviewed mapping")
            if set(headers) & {"_table_index", "_table_row"}:
                raise ValueError("HTML headers conflict with reserved evidence columns")
        else:
            headers = [f"column_{index + 1}" for index in range(len(headers))]
            data_rows = rows

        for values, subsequent_header, row_index in data_rows:
            if len(values) != len(headers) or subsequent_header:
                raise ValueError("Irregular HTML rows require a reviewed mapping")
            record = {
                headers[index] if index < len(headers) and headers[index]
                else f"column_{index + 1}": value
                for index, value in enumerate(values)
            }
            if record:
                record["_table_index"] = table_index
                record["_table_row"] = row_index
                records.append(record)
    return records


def parse_api_response(body, content_type=""):
    """Return a content-kind label and records without assuming a schema."""
    content_type = content_type.lower()
    stripped = body.lstrip()
    looks_like_json = stripped.startswith(("{", "["))

    if "json" in content_type or looks_like_json:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            if "json" in content_type:
                raise ValueError("API response declared JSON but is invalid")
        else:
            return "json", _json_records(payload)

    if "html" in content_type or stripped.lower().startswith(
        ("<!doctype html", "<html")
    ):
        soup = BeautifulSoup(body, "html.parser")
        records = _html_table_records(soup)
        if records:
            return "html_table", records
        text = soup.get_text(" ", strip=True)
        if text:
            return "html_text", [{"text": text}]
        raise ValueError("HTML response contains no text or table data")

    text = body.strip()
    if not text:
        raise ValueError("API response is empty")
    return "text", [{"text": text}]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused; review and submit the final HTTPS URL")


class BoundedApiReader:
    """Fetch explicitly allowlisted public hosts without scripts or credentials."""

    def __init__(self, *, allowed_hosts=(), timeout=15, opener=None):
        self.allowed_hosts = {str(host).strip().lower() for host in allowed_hosts}
        self.timeout = timeout
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def _validate(self, url):
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https" or not host or host not in self.allowed_hosts
            or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in (None, 443) or host == "localhost"
            or "." not in host
        ):
            raise ValueError("Use an allowlisted HTTPS host with no credentials or fragment")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return
        raise ValueError("IP-literal API endpoints are not accepted")

    def load(self, urls):
        if not 1 <= len(urls) <= MAX_URLS:
            raise ValueError(f"Supply 1–{MAX_URLS} API URLs")
        for url in urls:
            self._validate(url)
        responses = []
        for url in urls:
            request = Request(url, headers={
                "Accept": "application/json, text/html, text/plain",
                "Accept-Encoding": "identity",
                "User-Agent": "AgriAgent-SourceReview/1.0",
            })
            with self.opener.open(request, timeout=self.timeout) as response:
                media_type = response.headers.get_content_type()
                if not (media_type in {"application/json", "text/html", "text/plain"}
                        or media_type.endswith("+json")):
                    raise ValueError("Unsupported response type; use JSON, HTML or plain text")
                raw = response.read(MAX_BODY_BYTES + 1)
                if len(raw) > MAX_BODY_BYTES:
                    raise ValueError("Response exceeds the 2 MiB preview limit")
                body = raw.decode(response.headers.get_content_charset() or "utf-8-sig")
            kind, records = parse_api_response(body, media_type)
            if len(records) > MAX_RECORDS:
                raise ValueError("Response exceeds the 1,000-record limit; supply a bounded page")
            if kind == "html_table":
                locators = [
                    {"table": row["_table_index"] + 1, "row": row["_table_row"]}
                    for row in records
                ]
            elif kind == "json":
                payload = json.loads(body)
                key = next((key for key in _RECORD_KEYS if isinstance(payload, dict)
                            and isinstance(payload.get(key), list)), None)
                locators = [
                    {"json_path": f"$.{key}[{i}]" if key else f"$[{i}]"}
                    for i in range(len(records))
                ] if isinstance(payload, list) or key else [{"json_path": "$"}]
            else:
                locators = [{"scope": "response_body"}]
            responses.append({
                "source_url": url, "response_kind": kind, "records": records,
                "source_sha256": hashlib.sha256(raw).hexdigest(), "locators": locators,
            })
        return responses
