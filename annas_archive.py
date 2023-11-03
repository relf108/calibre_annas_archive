from contextlib import closing
from typing import Generator
from urllib.parse import quote_plus
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from http.client import RemoteDisconnected

from lxml import html
from lxml.etree import Comment

from calibre import browser
from calibre.gui2 import open_url
from calibre.gui2.store import StorePlugin
from calibre.gui2.store.basic_config import BasicStoreConfig
from calibre.gui2.store.search_result import SearchResult
from calibre.gui2.store.web_store_dialog import WebStoreDialog
from qt.core import QUrl

SearchResults = Generator[SearchResult, None, None]


class AnnasArchiveStore(BasicStoreConfig, StorePlugin):
    BASE_URL = 'https://annas-archive.org'

    @staticmethod
    def _search(url: str, max_results: int, timeout: int) -> SearchResults:
        br = browser()
        with closing(br.open(url, timeout=timeout)) as f:
            doc = html.fromstring(f.read())
            counter = max_results
            for data in doc.xpath('//div[@class="mb-4"]/div[contains(@class,"h-[125]")]'):
                if counter <= 0:
                    break

                book = data
                if not book.xpath('./*'):
                    comments = tuple(book.iterchildren(Comment))
                    if comments:
                        book = html.fromstring(html.tostring(comments[0]).strip(b'<!--').strip(b'-->'))
                    else:
                        continue

                hash_id = ''.join(url.split('/')[-1] for url in book.xpath('./a/@href'))
                if not hash_id:
                    continue

                s = SearchResult()
                s.detail_item = hash_id
                s.cover_url = ''.join(book.xpath('./a/div[contains(@class,"flex-none")]/div/img/@src'))
                s.title = ''.join(book.xpath('./a/div/h3/text()'))
                s.author = ''.join(book.xpath('./a/div/div[contains(@class,"italic")]/text()'))

                info = ''.join(book.xpath('./a/div/div[contains(@class,"text-gray-500")]/text()'))
                lang, format_, size, *filename = info.strip('"').split(',', 3)
                s.formats = format_.strip().upper()

                s.price = '$0.00'
                s.drm = SearchResult.DRM_UNLOCKED

                counter -= 1
                yield s

    def open(self, parent=None, detail_item=None, external=False):
        if detail_item:
            url = self._get_url(detail_item)
        else:
            url = self.BASE_URL
        if external or self.config.get('open_external', False):
            open_url(QUrl(url))
        else:
            d = WebStoreDialog(self.gui, self.BASE_URL, parent, url)
            d.setWindowTitle(self.name)
            d.set_tags(self.config.get('tags', ''))
            d.exec()

    @classmethod
    def search(cls, query, max_results=10, timeout=60) -> SearchResults:
        url = f'{cls.BASE_URL}/search?q={quote_plus(query)}'
        yield from cls._search(url, max_results, timeout)

    def get_details(self, search_result: SearchResult, timeout=60):
        if not search_result.formats:
            return

        _format = '.' + search_result.formats.lower()

        br = browser()
        with closing(br.open(self._get_url(search_result.detail_item), timeout=timeout)) as f:
            doc = html.fromstring(f.read())
            for link in doc.xpath('//div[@id="md5-panel-downloads"]/div/ul/li/a[contains(@class, "js-download-link")]'):
                url = link.get('href')

                # Speeds it up by checking the extension of the url.
                # Might miss a direct url that doesn't end with the extension
                if not url.endswith(_format):
                    continue
                if url[0] == '/':
                    url = self.BASE_URL + url
                try:
                    with urlopen(Request(url, method='HEAD'), timeout=timeout) as resp:
                        if resp.info().get_content_maintype() == 'application':
                            search_result.downloads[f"{search_result.formats} - {''.join(link.itertext())}"] = url
                except (HTTPError, URLError, TimeoutError, RemoteDisconnected):
                    pass

    def _get_url(self, md5):
        return f"{self.BASE_URL}/md5/{md5}"
