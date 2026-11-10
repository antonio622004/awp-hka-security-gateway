"""Uncached portal decisions, strict error contract and unchanged app assertions."""
import httpx
import pytest

from gateway.registry_client import RegistryClient, RegistryUnavailableError
from gateway.exceptions import ForbiddenError, NotFoundError, UnavailableError


@pytest.fixture
def build(tmp_path):
    secret = tmp_path / 'token'
    secret.write_text('t' * 43)
    clients = []
    def create(handler):
        client = RegistryClient('http://portal:8000', secret, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client
    yield create
    for client in clients:
        client.close()


def test_no_cache_service_auth_and_user_assertion(build):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'POST'
        assert str(request.url) == 'http://portal:8000/internal/apps/noten/authorize'
        assert request.headers['authorization'] == 'Bearer ' + 't' * 43
        assert request.headers['x-portal-assertion'] == 'signed-context'
        assert 'cookie' not in request.headers
        if len(calls) == 2:
            return httpx.Response(403, json={'slug': 'noten', 'allowed': False, 'reason': 'forbidden'})
        return httpx.Response(200, json={'slug': 'noten', 'allowed': True, 'adapters': ['noten:read']},
                              headers={'Set-Cookie': 'foreign=secret'})
    client = build(handler)
    assert client.authorize('noten', 'signed-context').adapters == ('noten:read',)
    with pytest.raises(ForbiddenError):
        client.authorize('noten', 'signed-context')
    assert len(calls) == 2


@pytest.mark.parametrize('status,reason,error', [(403, 'forbidden', ForbiddenError),
                         (404, 'not_found', NotFoundError), (503, 'unavailable', UnavailableError)])
def test_explicit_denials(build, status, reason, error):
    client = build(lambda request: httpx.Response(status, json={'slug': 'noten', 'allowed': False, 'reason': reason}))
    with pytest.raises(error):
        client.authorize('noten', 'context')


@pytest.mark.parametrize('status,data', [
    (200, {}), (200, None), (200, []), (200, {'slug': 'noten', 'allowed': False, 'adapters': []}),
    (200, {'slug': 'other', 'allowed': True, 'adapters': []}),
    (200, {'slug': 'noten', 'allowed': 1, 'adapters': []}),
    (200, {'slug': 'noten', 'allowed': True, 'adapters': ['invalid']}),
    (200, {'slug': 'noten', 'allowed': True, 'adapters': [], 'upstream': 'http://evil'}),
    (401, {'error': 'service_authentication'}), (403, {'error': 'service_authentication'}),
    (404, {'detail': 'Not Found'}), (503, {}), (302, {})])
def test_invalid_decisions_fail_closed(build, status, data):
    client = build(lambda request: httpx.Response(status, json=data))
    with pytest.raises(RegistryUnavailableError):
        client.authorize('noten', 'context')


def test_timeout_and_oversize_fail_closed(build):
    def timeout(request):
        raise httpx.ReadTimeout('unavailable')
    for handler in (timeout, lambda request: httpx.Response(200, content=b'x' * 65537,
                                                           headers={'Content-Type': 'application/json'})):
        with pytest.raises(RegistryUnavailableError):
            build(handler).authorize('noten', 'context')
