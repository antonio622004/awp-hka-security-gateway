"""Quelltext eines Moduls ohne seine Imports ausführen; die Abhängigkeiten liefert der Test.

So laufen Klassen und Funktionen unverändert, isoliert von Paket-Initialisierung (genutzt von test_proxy.py).
Früher Teil von test_parity.py.
"""
import ast
import base64
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Final, Mapping
import unittest
import uuid
from urllib.parse import quote

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from gateway.config import AssertionConfig, ConfigError
from gateway.exceptions import (LoginFailedError, LoginRequiredError, ForbiddenError, NotFoundError, UnavailableError)
from gateway.redirects import sanitize_next

GATEWAY = Path(__file__).resolve().parents[1] / 'src/gateway'


def source_module(path, **dependencies):
    if not path.exists():
        raise unittest.SkipTest(f'Portal comparison source unavailable: {path}')
    module = ModuleType('_parity_' + path.stem + '_' + str(abs(hash(path))))
    sys.modules[module.__name__] = module
    module.__dict__.update({
        'dataclass': dataclass, 'field': field, 'Any': Any, 'Final': Final, 'Mapping': Mapping,
        'Path': Path, 'jwt': jwt, 'serialization': serialization, 'rsa': rsa, 'RSAAlgorithm': RSAAlgorithm,
        'base64': base64, 'hashlib': hashlib, 'json': json, 'time': time, 'uuid': uuid, 'secrets': secrets,
        'quote': quote, 'logger': SimpleNamespace(debug=lambda *a: None, info=lambda *a: None,
                                                warning=lambda *a: None),
        'AssertionConfig': AssertionConfig, 'ConfigError': ConfigError, 'TOKEN_VERSION': 1,
        'sanitize_next': sanitize_next, 'LoginFailedError': LoginFailedError, 'OidcError': RuntimeError,
        'LoginRequiredError': LoginRequiredError, 'ForbiddenError': ForbiddenError,
        'NotFoundError': NotFoundError, 'UnavailableError': UnavailableError, 'AppDTO': lambda app: app,
    })
    module.__dict__.update(dependencies)
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))
                 or isinstance(node, ast.ImportFrom) and node.module == '__future__']
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module
