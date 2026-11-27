"""Proxy regression tests with real HTTPX/Starlette and in-memory upstreams.

The existing source-isolation harness supplies actual Starlette aliases for the
FastAPI re-exports and a no-op logger. No FastAPI app or services are started.
"""
import asyncio
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit
import unittest

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException

from gateway.config import AppsConfig
from gateway.exceptions import UnavailableError
from source_loader import GATEWAY, source_module

proxy_module = source_module(GATEWAY / 'proxy.py', CookieJar=CookieJar, DefaultCookiePolicy=DefaultCookiePolicy,
                             httpx=httpx, Request=Request, Response=Response, StreamingResponse=StreamingResponse,
                             BackgroundTask=BackgroundTask, HTTPException=HTTPException, AppsConfig=AppsConfig,
                             UnavailableError=UnavailableError, urlsplit=urlsplit)


def request(slug='noten', *, headers=(), method='GET', body=b''):
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    scope = {'type': 'http', 'method': method, 'scheme': 'https', 'path': f'/apps/{slug}/',
             'raw_path': f'/apps/{slug}/'.encode(), 'query_string': b'q=1',
             'server': ('gateway.test', 443), 'client': ('192.0.2.1', 1234),
             'headers': [(b'host', b'gateway.test'), *headers]}
    value = Request(scope, receive)
    value.state.request_id = 'test-request-id'
    return value


async def consume(response):
    body = b''.join([chunk async for chunk in response.body_iterator])
    if response.background:
        await response.background()
    return body


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    def proxy(self, handler, cfg=None):
        result = proxy_module.AppProxy(cfg or AppsConfig('http://{slug}.apps.test:8080'),
                                       httpx.MockTransport(handler))
        self.addAsyncCleanup(result.aclose)
        return result

    async def test_authorization_cookies_and_forged_assertions_are_removed(self):
        seen = []
        def upstream(req):
            seen.append(req)
            return httpx.Response(200, content=b'body', headers={'Set-Cookie': 'app=secret; Path=/'})
        proxy = self.proxy(upstream)
        response = await proxy.forward(request(headers=[(b'Authorization', b'Bearer browser-token'),
                                                        (b'authorization', b'Basic second-token'),
                                                        (b'cookie', b'portal_sid=browser-secret'),
                                                        (b'x-portal-assertion', b'forged')]), 'noten', 'signed-assertion')
        self.assertEqual(await consume(response), b'body')
        self.assertNotIn('authorization', seen[0].headers)
        self.assertNotIn('cookie', seen[0].headers)
        self.assertEqual(seen[0].headers.get_list('x-portal-assertion'), ['signed-assertion'])
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(list(proxy.client.cookies.jar), [])

    async def test_language_replaces_accept_language(self):
        seen = []
        def upstream(req):
            seen.append(req)
            return httpx.Response(200, content=b'body')
        proxy = self.proxy(upstream)
        await consume(await proxy.forward(request(headers=[(b'accept-language', b'fr-FR,fr;q=0.9')]), 'noten', 'token',
                                          language='en'))
        self.assertEqual(seen[0].headers.get_list('accept-language'), ['en'])
        await consume(await proxy.forward(request(headers=[(b'accept-language', b'fr-FR')]), 'noten', 'token'))
        self.assertEqual(seen[1].headers.get_list('accept-language'), ['fr-FR'])  # ohne language unverändert
        await consume(await proxy.forward(request(), 'noten', 'token', language='de'))
        self.assertEqual(seen[2].headers.get_list('accept-language'), ['de'])

    async def test_no_cookie_storage_or_reuse_for_next_user_on_same_upstream(self):
        seen = []
        def upstream(req):
            seen.append(req)
            return httpx.Response(200, content=b'body', headers={'Set-Cookie': 'user=first; Path=/'})
        proxy = self.proxy(upstream)
        for user in ('first', 'second', 'third'):
            response = await proxy.forward(request(), 'noten', user + '-assertion')
            # Test storage immediately, rather than merely absence on the next send.
            self.assertEqual(list(proxy.client.cookies.jar), [])
            await consume(response)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all('cookie' not in req.headers for req in seen))

    async def test_no_domain_cookie_storage_or_reuse_across_upstreams(self):
        seen = []
        def upstream(req):
            seen.append(req)
            return httpx.Response(200, content=b'body', headers=[
                ('Set-Cookie', 'shared=secret; Domain=.apps.test; Path=/'),
                ('Set-Cookie', 'hostonly=secret; Path=/'),
            ])
        proxy = self.proxy(upstream)
        for slug in ('noten', 'kalender', 'noten'):
            response = await proxy.forward(request(slug), slug, 'assertion')
            self.assertEqual(list(proxy.client.cookies.jar), [])
            self.assertNotIn('set-cookie', response.headers)
            await consume(response)
        self.assertEqual([req.url.host for req in seen], ['noten.apps.test', 'kalender.apps.test', 'noten.apps.test'])
        self.assertTrue(all('cookie' not in req.headers for req in seen))

    async def test_parallel_requests_do_not_share_cookie_state(self):
        seen = []
        async def upstream(req):
            await asyncio.sleep(0)
            seen.append(req)
            return httpx.Response(200, content=b'body', headers={'Set-Cookie': 'shared=secret; Domain=.apps.test; Path=/'})
        proxy = self.proxy(upstream)
        async def forward(index):
            slug = 'noten' if index % 2 else 'kalender'
            response = await proxy.forward(request(slug), slug, f'user-{index}')
            await consume(response)
        await asyncio.gather(*(forward(i) for i in range(12)))
        self.assertEqual(len(seen), 12)
        self.assertEqual(list(proxy.client.cookies.jar), [])
        self.assertTrue(all('cookie' not in req.headers for req in seen))

    async def test_existing_path_query_body_and_location_behavior(self):
        seen = []
        def upstream(req):
            seen.append(req)
            return httpx.Response(302, content=b'body', headers={'Location': 'http://noten.apps.test:8080/apps/noten/next'})
        proxy = self.proxy(upstream)
        response = await proxy.forward(request(method='POST', body=b'payload'), 'noten', 'assertion')
        self.assertEqual(str(seen[0].url), 'http://noten.apps.test:8080/apps/noten/?q=1')
        self.assertEqual(seen[0].content, b'payload')
        self.assertEqual(seen[0].method, 'POST')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], '/apps/noten/next')
        self.assertEqual(await consume(response), b'body')

    async def test_existing_body_limit_and_upstream_error_mapping(self):
        seen = []
        proxy = self.proxy(lambda req: seen.append(req), AppsConfig('http://noten.apps.test', max_body_bytes=4))
        with self.assertRaises(HTTPException) as error:
            await proxy.forward(request(method='POST', body=b'oversized'), 'noten', 'assertion')
        self.assertEqual(error.exception.status_code, 413)
        self.assertEqual(seen, [])
        for error_type, expected in ((httpx.ConnectError, UnavailableError), (httpx.ReadTimeout, 504),
                                     (httpx.ReadError, 502)):
            def fail(req):
                raise error_type('upstream failed', request=req)
            with self.subTest(error=error_type):
                proxy = self.proxy(fail)
                if isinstance(expected, int):
                    with self.assertRaises(HTTPException) as error:
                        await proxy.forward(request(), 'noten', 'assertion')
                    self.assertEqual(error.exception.status_code, expected)
                else:
                    with self.assertRaises(expected):
                        await proxy.forward(request(), 'noten', 'assertion')


if __name__ == '__main__':
    unittest.main()
