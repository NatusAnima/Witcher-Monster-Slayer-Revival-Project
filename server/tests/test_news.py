"""HTTP news contract and recovery tests, using only temporary authored fixtures."""
import concurrent.futures
import copy
import json
import struct
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from test_prototype import Server


def feed(title='Wiadomość: zażółć gęślą jaźń', item_id=1):
    return {'news_list': [{'id': item_id, 'group_id': 'sample-news-' + str(item_id), 'title': title,
                        'short_description': 'Test', 'date': '30/09/2026', 'image_url': '',
                        'content': 'Pierwszy akapit.\nDrugi akapit.'}], 'featured': item_id}


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.news = self.directory / 'news'
        self.news.mkdir()
        self.write('pl', feed())
        self.server = Server(self.directory, 'synthetic-news', {'News__Directory': str(self.news)})
        self.addCleanup(self.server.stop)

    def write(self, language, document):
        staged = self.news / (language + '.pending')
        staged.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        staged.replace(self.news / (language + '.json'))

    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}' + path, timeout=3) as response:
            return json.loads(response.read()), response.headers

    def raw(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}' + path, timeout=3) as response:
            return response.read(), response.headers

    def served(self, document):
        """The feed as the client receives it: image file names become URLs on the address it asked."""
        document = copy.deepcopy(document)
        for item in document['news_list']:
            if '://' not in item['image_url']:
                item['image_url'] = (f'http://127.0.0.1:{self.server.http}/news/images/'
                                     + (item['image_url'] or 'default.png'))
        return document

    def test_client_contract_language_routes_and_no_cache(self):
        expected = self.served(feed())
        for route in ['/news', '/news/pl', '/news/pl/']:
            with self.subTest(route=route):
                actual, headers = self.get(route)
                self.assertEqual(actual, expected)
                self.assertEqual(headers['Content-Language'], 'pl')
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertIn('application/json', headers['Content-Type'])
                self.assertIn('charset=utf-8', headers['Content-Type'])

    def test_updates_without_restart_and_localization_fallback(self):
        self.write('en', feed('English'))
        self.assertEqual(self.get('/news/en-US')[0]['news_list'][0]['title'], 'English')
        self.assertEqual(self.get('/news/de')[1]['Content-Language'], 'pl')
        process = self.server.process.pid
        self.write('pl', feed('Nowy komunikat', 2))
        self.assertEqual(self.get('/news/pl')[0], self.served(feed('Nowy komunikat', 2)))
        self.assertEqual(self.server.process.pid, process)

    def test_invalid_partial_file_and_deleted_file_keep_last_valid(self):
        expected = self.get('/news/pl')[0]
        (self.news / 'pl.json').write_text('{"news_list":', encoding='utf-8')
        self.assertEqual(self.get('/news/pl')[0], expected)
        (self.news / 'pl.json').unlink()
        self.assertEqual(self.get('/news/pl')[0], expected)
        self.assertEqual(self.server.get('/health')['status'], 'ready')
        self.write('pl', feed('Recovered', 3))
        self.assertEqual(self.get('/news/pl')[0], self.served(feed('Recovered', 3)))

    def test_unsafe_client_data_cannot_replace_a_valid_feed(self):
        expected = self.get('/news/pl')[0]
        invalid = []
        for key, value in [('date', '2026-09-30'), ('date', '31/02/2026'), ('date', '٣٠/٠٩/٢٠٢٦'),
                           ('group_id', 'bad;state'), ('image_url', 'file:///tmp/image'), ('title', None),
                           ('content', None), ('id', 0), ('image_url', 'cover.gif'), ('image_url', '../pl.json')]:
            document = feed()
            document['news_list'][0][key] = value
            invalid.append(document)
        duplicate = feed(); duplicate['news_list'].append(copy.deepcopy(duplicate['news_list'][0]))
        invalid += [duplicate, {'news_list': None, 'featured': 0},
                    {'news_list': [], 'featured': 99}, {'news_list': [None], 'featured': 0}]
        missing = feed(); del missing['news_list'][0]['content']; invalid.append(missing)
        # The C# field names are not the client's JSON names; Newtonsoft would leave news_list null.
        invalid.append({'NewsList': feed()['news_list'], 'HighlightedId': 0})
        for document in invalid:
            with self.subTest(document=document):
                self.write('pl', document)
                self.assertEqual(self.get('/news/pl')[0], expected)
                self.assertIsNone(self.server.process.poll())

    def test_oversized_feed_keeps_last_valid(self):
        expected = self.get('/news/pl')[0]
        self.write('pl', feed('a' * (1024 * 1024 + 1)))
        self.assertEqual(self.get('/news/pl')[0], expected)

    def test_no_valid_feed_returns_retry_status_and_server_stays_ready(self):
        (self.news / 'pl.json').write_text('not JSON', encoding='utf-8')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get('/news/pl')
        self.assertEqual(caught.exception.code, 503)
        self.assertEqual(json.loads(caught.exception.read()), {'news_list': [], 'featured': 0})
        caught.exception.close()
        self.assertEqual(self.server.get('/health')['status'], 'ready')

    def test_localized_feed_falls_back_when_invalid_before_first_read(self):
        (self.news / 'en.json').write_text('null', encoding='utf-8')
        self.assertEqual(self.get('/news/en')[0], self.served(feed()))

    def test_parallel_requests_survive_atomic_update(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            pending = [pool.submit(self.get, '/news/pl') for _ in range(20)]
            self.write('pl', feed('New edition', 2))
            for job in pending:
                document = job.result()[0]
                self.assertIn(document['featured'], [1, 2])
                self.assertEqual(len(document['news_list']), 1)

    def test_empty_feed_and_path_input_do_not_break_the_server(self):
        self.write('pl', {'news_list': [], 'featured': 0})
        self.assertEqual(self.get('/news/pl')[0], {'news_list': [], 'featured': 0})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get('/news/pl.json')
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        self.assertEqual(self.server.get('/health')['status'], 'ready')

    def test_cover_images_are_served_on_the_address_the_client_used(self):
        # LazyNewsHubEntry waits for a cover texture, so every served entry has an image URL.
        (self.news / 'images').mkdir()
        (self.news / 'images' / 'cover.png').write_bytes(b'\x89PNG-operator-cover')
        document = feed(); document['news_list'][0]['image_url'] = 'cover.png'
        self.write('pl', document)
        base = f'http://127.0.0.1:{self.server.http}/news/images/'
        self.assertEqual(self.get('/news/pl')[0]['news_list'][0]['image_url'], base + 'cover.png')
        body, headers = self.raw('/news/images/cover.png')
        self.assertEqual((body, headers['Content-Type']), (b'\x89PNG-operator-cover', 'image/png'))
        absolute = feed(); absolute['news_list'][0]['image_url'] = 'https://example.test/cover.jpg'
        self.write('pl', absolute)
        self.assertEqual(self.get('/news/pl')[0]['news_list'][0]['image_url'], 'https://example.test/cover.jpg')
        for path, code in [('/news/images/missing.png', 404), ('/news/images/cover.gif', 400),
                           ('/news/images/..%2Fpl.json', 400)]:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as caught:
                self.raw(path)
            self.assertEqual(caught.exception.code, code)
            caught.exception.close()

    def test_generated_default_cover_is_a_valid_png(self):
        self.assertEqual(self.get('/news/pl')[0]['news_list'][0]['image_url'],
                         f'http://127.0.0.1:{self.server.http}/news/images/default.png')
        body, headers = self.raw('/news/images/default.png')
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(body[:8], b'\x89PNG\r\n\x1a\n')
        chunks, offset = {}, 8
        while offset < len(body):
            length, kind = struct.unpack('>I4s', body[offset:offset + 8])
            data = body[offset + 8:offset + 8 + length]
            self.assertEqual(struct.unpack('>I', body[offset + 8 + length:offset + 12 + length])[0],
                             zlib.crc32(kind + data))
            chunks[kind] = data
            offset += 12 + length
        width, height, depth, colour = struct.unpack('>IIBB', chunks[b'IHDR'][:10])
        self.assertEqual((width, height, depth, colour), (1024, 512, 8, 2))
        self.assertEqual(len(zlib.decompress(chunks[b'IDAT'])), height * (1 + width * 3))
        self.assertIn(b'IEND', chunks)

    def test_default_packaged_feed_is_available(self):
        other = Server(self.directory, 'synthetic-packaged-news')
        self.addCleanup(other.stop)
        document = other.get('/news/pl')
        self.assertEqual(document['news_list'][0]['group_id'], 'revival-news-preview-20260930')
        self.assertEqual(document['featured'], document['news_list'][0]['id'])
