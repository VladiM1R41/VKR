"""Universal RSS collector for Layer 1 MVP."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from jarvis.db.models import Source
from jarvis.ingestion.collectors.base import BaseCollector
from jarvis.ingestion.contracts.normalized_article import NormalizedArticle
from jarvis.ingestion.extraction import ensure_lxml_available
from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules
from jarvis.ingestion.extraction.rss_fulltext import extract_rss_fulltext
from jarvis.ingestion.mappings.source_taxonomy import map_content_type, map_information_type
from jarvis.ingestion.network.http_client import decode_response_text, fetch_with_retry
from jarvis.ingestion.parsing.dates import parse_feed_datetime
from jarvis.ingestion.parsing.routing import detect_breaking
from jarvis.ingestion.parsing.urls import canonicalize_url, normalized_title_hash


DEFAULT_USER_AGENT = "JarvisLayer1/0.1 (+research project; contact: local-dev)"


class RSSCollector(BaseCollector):
    """Universal RSS collector using BS4 XML as the single production path."""

    def __init__(self, source: Source, http_client, known_canonical_urls: set[str] | None = None):
        super().__init__(source, http_client, known_canonical_urls=known_canonical_urls)
        self.last_items_total = 0
        self.last_response_bytes = 0
        self.last_http_status: int | None = None
        self.last_parse_errors = 0
        self.last_item_failures = 0
        self.last_date_parse_warnings = 0
        self.last_item_errors: list[dict[str, str | int | None]] = []
        self.last_was_not_modified = False
        self.last_was_same_build_date = False
        self.last_sent_etag: str | None = None
        self.last_sent_if_modified_since: str | None = None
        self.last_received_etag: str | None = None
        self.last_received_last_modified: str | None = None
        self.last_received_last_build_date: str | None = None

    async def collect(self) -> list[NormalizedArticle]:
        feed_url = self.config.get("feed_url") or self.source.url
        request_headers = {"User-Agent": DEFAULT_USER_AGENT}
        request_headers.update(self._build_conditional_headers())

        self.last_was_not_modified = False
        self.last_was_same_build_date = False
        self.last_sent_etag = None
        self.last_sent_if_modified_since = None
        self.last_received_etag = None
        self.last_received_last_modified = None
        self.last_received_last_build_date = None
        self.last_known_duplicates_skipped = 0

        response = await fetch_with_retry(
            self.http,
            feed_url,
            headers=request_headers,
        )

        self.last_http_status = response.status_code
        self.last_received_etag = response.headers.get("ETag")
        self.last_received_last_modified = response.headers.get("Last-Modified")

        if response.status_code == 304:
            self.last_was_not_modified = True
            self.last_response_bytes = 0
            self.last_items_total = 0
            return []

        response.raise_for_status()
        self.last_response_bytes = len(response.content)

        ensure_lxml_available()
        feed_text = decode_response_text(response)
        soup = BeautifulSoup(feed_text, "xml")
        channel = soup.find("channel")
        items = soup.find_all("item", recursive=False)
        if not items and channel:
            items = channel.find_all("item", recursive=False)

        self.last_received_last_build_date = self._extract_last_build_date(channel)
        if self._should_skip_on_same_last_build_date():
            self.last_was_same_build_date = True
            self.last_items_total = 0
            return []

        self.last_items_total = len(items)
        articles: list[NormalizedArticle] = []
        processing_items = self._sort_items_for_processing(items) if self.config.get("stop_early_on_known") else items
        if self.config.get("stop_early_on_known"):
            self.last_known_duplicates_skipped = self._count_known_duplicate_candidates(processing_items)

        for item in processing_items:
            if self.config.get("stop_early_on_known"):
                candidate_url = self._peek_canonical_url(item)
                if candidate_url and candidate_url in self.known_canonical_urls:
                    break

            try:
                article = self._parse_item(item)
            except Exception as exc:
                self.last_parse_errors += 1
                self.last_item_failures += 1
                self._record_item_error(
                    error_type="rss_parse",
                    error_message=f"{type(exc).__name__}: {exc}",
                    item_url=self._extract_item_url(item),
                )
                continue

            if article is not None:
                articles.append(article)

        return articles

    def _should_skip_on_same_last_build_date(self) -> bool:
        if not self.config.get("has_last_build_date"):
            return False

        stored_value = str(self.config.get("last_build_date_value") or "").strip()
        current_value = str(self.last_received_last_build_date or "").strip()
        return bool(stored_value and current_value and stored_value == current_value)

    def _build_conditional_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}

        if self.config.get("supports_etag"):
            etag_value = (self.config.get("etag_value") or "").strip()
            if etag_value:
                headers["If-None-Match"] = etag_value
                self.last_sent_etag = etag_value

        if self.config.get("supports_last_modified"):
            last_modified_value = (self.config.get("last_modified_value") or "").strip()
            if last_modified_value:
                headers["If-Modified-Since"] = last_modified_value
                self.last_sent_if_modified_since = last_modified_value

        return headers

    def _parse_item(self, item: Tag) -> NormalizedArticle | None:
        source_key = self.config.get("source_key")
        title = self._get_top_level_text(item, "title")
        if not title:
            self.last_item_failures += 1
            self._record_item_error(
                error_type="data_missing",
                error_message="Missing required title",
                item_url=self._extract_item_url(item),
            )
            return None

        url = self._extract_item_url(item)
        if not url:
            self.last_item_failures += 1
            self._record_item_error(
                error_type="data_missing",
                error_message="Missing required URL",
                item_url=None,
            )
            return None

        canonical_url = canonicalize_url(
            url,
            keep_params=self.config.get("canonical_keep_params", []),
        )
        if not canonical_url:
            self.last_item_failures += 1
            self._record_item_error(
                error_type="data_missing",
                error_message="Failed to build canonical URL",
                item_url=url,
            )
            return None

        raw_pub_date = self._extract_pub_date(item)
        published_at, date_inferred = parse_feed_datetime(raw_pub_date)
        if raw_pub_date and published_at is None:
            self.last_date_parse_warnings += 1
            self._record_item_error(
                error_type="date_parse",
                error_message=f"Could not parse pub date: {raw_pub_date}",
                item_url=canonical_url,
            )

        description_html = self._get_description_html(item)
        snippet_lead = self._html_to_text(description_html) if description_html else None
        full_text_html = self._get_direct_tag_html(item, self.config.get("full_text_tag"))
        postprocess_rules = list(self.config.get("postprocess_rules") or [])

        extra: dict = {}
        raw_title = title.strip()
        split_delimiter = str(self.config.get("split_title_on") or "").strip()
        if split_delimiter:
            _, subtitle = self._split_title_with_subtitle(raw_title, split_delimiter)
            if subtitle:
                extra["subtitle"] = subtitle

        if self.config.get("mixed_regional_hosts"):
            source_host = self._extract_source_host(url)
            if source_host:
                extra["source_host"] = source_host

        raw_source_content_type: str | None = None
        raw_source_information_type: str | None = None

        author = self._get_top_level_text(item, "author")
        if author:
            author = author.strip()
            author_format = self.config.get("author_format", "absent")
            if author_format == "channel_name":
                extra["channel_name"] = author
            else:
                extra["author"] = author

        categories = [tag.get_text(strip=True) for tag in item.find_all("category", recursive=False)]
        categories = [category for category in categories if category]
        if categories:
            extra["categories"] = categories

        enclosure = item.find("enclosure", recursive=False)
        if enclosure and enclosure.get("url"):
            extra["thumbnail"] = enclosure.get("url", "").strip()

        rss_fulltext = extract_rss_fulltext(
            item=item,
            method=self.config.get("full_text_method", "html_trafilatura"),
            config=self.config,
            full_text_html=full_text_html,
            description_html=description_html,
            thumbnail_url=extra.get("thumbnail"),
        )
        extra.update(rss_fulltext.get("extra") or {})
        if not snippet_lead and rss_fulltext.get("content"):
            snippet_lead = self._build_snippet_from_content(rss_fulltext["content"])

        if source_key == "rbc":
            pdalink = self._get_top_level_text(item, "pdalink")
            if pdalink:
                canonical_url = canonicalize_url(
                    pdalink,
                    keep_params=self.config.get("canonical_keep_params", []),
                )
                url = pdalink

            rbc_tags = [
                tag.get_text(strip=True)
                for tag in item.find_all("rbc_news:tag", recursive=False)
                if tag.get_text(strip=True)
            ]
            if rbc_tags:
                extra["rbc_tags"] = rbc_tags

            newsline = self._get_top_level_text(item, "rbc_news:newsline")
            if newsline:
                extra["rbc_newsline"] = newsline

            rbc_type = self._get_top_level_text(item, "rbc_news:type")
            if rbc_type:
                extra["source_content_type"] = rbc_type
                raw_source_content_type = rbc_type

        if source_key == "ria":
            rian_type = self._get_top_level_text(item, "rian:type")
            if rian_type:
                extra["source_content_type"] = rian_type
                raw_source_content_type = rian_type

            rian_priority = self._get_top_level_text(item, "rian:priority")
            if rian_priority:
                try:
                    extra["rian_priority"] = int(rian_priority)
                except ValueError:
                    extra["rian_priority"] = rian_priority

        information_type = map_information_type(
            source_key,
            raw_source_information_type,
            self.source.default_info_type,
        )
        content_type = map_content_type(
            source_key,
            raw_source_content_type,
            self.source.default_content_type,
        )

        author = extra.get("author")
        if source_key == "ixbt" and author:
            cleaned_author = self._extract_ixbt_author(author)
            if cleaned_author:
                extra["author"] = cleaned_author

        if source_key == "rt":
            section = self._extract_url_section(canonical_url)
            if section:
                extra["rt_section"] = section

        if self.config.get("read_theme_tags"):
            theme_tags = self._get_top_level_text(item, "yandex:theme_tags")
            if theme_tags:
                extra["yandex_story_tag"] = theme_tags

        if self.config.get("read_related_links"):
            related_links = self._extract_related_links(item)
            if related_links:
                related_urls = [link["url"] for link in related_links if link.get("url")]
                related_titles = [
                    title
                    for link in related_links
                    if (title := link.get("title"))
                ]
                if related_urls:
                    extra["source_related_urls"] = related_urls
                if related_titles:
                    extra["source_related_titles"] = related_titles

        urgency = "normal"
        if detect_breaking(raw_title):
            information_type = "breaking"
            urgency = "high"
            extra["information_type_override"] = "pre_classifier_breaking"
            extra["urgency"] = urgency

        cleaned_content, cleaned_snippet = apply_postprocess_rules(
            content=rss_fulltext.get("content"),
            snippet_lead=snippet_lead,
            rules=postprocess_rules,
        )

        return NormalizedArticle(
            source_id=self.source.id,
            url=url,
            canonical_url=canonical_url,
            title=raw_title,
            channel_type="RSS",
            published_at=published_at,
            raw_pub_date=raw_pub_date,
            content=cleaned_content,
            snippet_lead=cleaned_snippet,
            title_hash=normalized_title_hash(title),
            content_status=rss_fulltext.get("content_status") or "partial",
            extraction_method=rss_fulltext.get("extraction_method"),
            information_type=information_type,
            content_type=content_type,
            language="ru",
            urgency=urgency,
            raw_content=rss_fulltext.get("raw_content"),
            raw_format=rss_fulltext.get("raw_format") or "html",
            date_inferred=date_inferred,
            parser_version=self.get_parser_version(),
            extra=extra,
        )

    def _extract_item_url(self, item: Tag) -> str | None:
        if self.config.get("use_guid_as_url"):
            return self._get_top_level_text(item, "guid")

        field = self.config.get("url_source_field", "link")
        return self._get_top_level_text(item, field)

    def _peek_canonical_url(self, item: Tag) -> str | None:
        url = self._extract_item_url(item)
        if not url:
            return None
        return canonicalize_url(
            url,
            keep_params=self.config.get("canonical_keep_params", []),
        )

    @staticmethod
    def _get_top_level_text(item: Tag, tag_name: str) -> str | None:
        tag = RSSCollector._find_direct_child(item, tag_name)
        if tag is None:
            return None
        text = tag.get_text(strip=True)
        return text or None

    @staticmethod
    def _extract_pub_date(item: Tag) -> str | None:
        return (
            RSSCollector._get_top_level_text(item, "pubDate")
            or RSSCollector._get_top_level_text(item, "published")
            or RSSCollector._get_top_level_text(item, "updated")
        )

    @staticmethod
    def _extract_last_build_date(channel: Tag | None) -> str | None:
        if channel is None:
            return None
        return RSSCollector._get_top_level_text(channel, "lastBuildDate")

    @staticmethod
    def _extract_related_links(item: Tag) -> list[dict[str, str | None]]:
        related = (
            RSSCollector._find_direct_child(item, "rbc_news:related_links")
            or RSSCollector._find_direct_child(item, "yandex:related")
        )
        if related is None:
            return []

        links: list[dict[str, str | None]] = []
        for link in related.find_all("link", recursive=False):
            url = (link.get("url") or link.get("href") or "").strip()
            title = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
            img = (link.get("img") or "").strip() or None
            if not url:
                continue
            links.append({"url": url, "title": title or None, "img": img})
        return links

    @staticmethod
    def _get_description_html(item: Tag) -> str | None:
        tag = item.find("description", recursive=False) or item.find("summary", recursive=False)
        if tag is None:
            return None
        raw = tag.decode_contents().strip()
        return raw or None

    @staticmethod
    def _get_direct_tag_html(item: Tag, tag_name: str | None) -> str | None:
        child = RSSCollector._find_direct_child(item, tag_name)
        if child is not None:
            raw = child.decode_contents().strip()
            return raw or None
        return None

    @staticmethod
    def _find_direct_child(item: Tag, tag_name: str | None) -> Tag | None:
        if not tag_name:
            return None

        expected = tag_name.strip()
        expected_suffix = expected.split(":", 1)[-1]
        for child in item.children:
            child_name = getattr(child, "name", None)
            if not child_name:
                continue
            if child_name == expected or child_name == expected_suffix:
                return child
        return None

    @staticmethod
    def _html_to_text(raw_html: str) -> str:
        unescaped = html.unescape(raw_html)
        if "<" not in unescaped and ">" not in unescaped:
            return unescaped.strip()

        text = BeautifulSoup(unescaped, "html.parser").get_text(" ", strip=True)
        text = html.unescape(text)
        return text.strip()

    @staticmethod
    def _extract_ixbt_author(raw_author: str) -> str | None:
        match = re.search(r"\(([^)]+)\)", raw_author)
        if match:
            return match.group(1).strip()
        if "@" in raw_author:
            return raw_author.split("@", 1)[0].strip() or None
        cleaned = raw_author.strip()
        return cleaned or None

    @staticmethod
    def _extract_url_section(url: str) -> str | None:
        match = re.match(r"^https?://[^/]+/([^/?#]+)/", url)
        if not match:
            return None
        section = match.group(1).strip().lower()
        return section or None

    @staticmethod
    def _build_snippet_from_content(content: str) -> str | None:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        for line in lines:
            if len(line) >= 30:
                return line[:400]
        return lines[0][:400] if lines else None

    @staticmethod
    def _split_title_with_subtitle(raw_title: str, delimiter: str) -> tuple[str, str | None]:
        if delimiter and delimiter in raw_title:
            head, tail = raw_title.split(delimiter, 1)
            return head.strip(), tail.strip() or None
        return raw_title, None

    @staticmethod
    def _extract_source_host(url: str) -> str | None:
        host = (urlsplit(url).hostname or "").strip().lower()
        return host or None

    @staticmethod
    def _sort_items_for_processing(items: list[Tag]) -> list[Tag]:
        def _sort_key(indexed_item: tuple[int, Tag]) -> tuple[float, int]:
            index, item = indexed_item
            raw_pub_date = RSSCollector._extract_pub_date(item)
            published_at, _ = parse_feed_datetime(raw_pub_date)
            timestamp = published_at.timestamp() if published_at else float("-inf")
            return timestamp, -index

        if len(items) < 2:
            return items

        return [item for _, item in sorted(enumerate(items), key=_sort_key, reverse=True)]

    def _count_known_duplicate_candidates(self, items: list[Tag]) -> int:
        duplicates = 0
        for item in items:
            candidate_url = self._peek_canonical_url(item)
            if candidate_url and candidate_url in self.known_canonical_urls:
                duplicates += 1
        return duplicates

    def _record_item_error(
        self,
        *,
        error_type: str,
        error_message: str,
        item_url: str | None,
        http_status: int | None = None,
    ) -> None:
        self.last_item_errors.append(
            {
                "error_type": error_type,
                "error_message": error_message,
                "item_url": item_url,
                "http_status": http_status,
            }
        )
