"""Nomba API service integration for checkout and recurring charges."""
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_nomba_token_cache: Dict[str, Any] = {
    'access_token': None,
    'expiry': 0,
}


class NombaAPIError(Exception):
    """Raised when a Nomba API request fails."""

    def __init__(self, code: str, description: str):
        super().__init__(description)
        self.code = code
        self.description = description


class NombaClient:
    """Thin wrapper around the Nomba payment API with async auth token fetching."""

    def __init__(self):
        self.base_url = settings.NOMBA_BASE_URL.rstrip('/')
        self.account_id = settings.NOMBA_ACCOUNT_ID
        self.client_id = settings.NOMBA_CLIENT_ID
        self.client_secret = settings.NOMBA_CLIENT_SECRET

    async def get_access_token(self) -> str:
        """Fetch a new Bearer token or return a cached one if still valid."""
        if _nomba_token_cache['access_token'] and time.time() < (_nomba_token_cache['expiry'] - 300):
            return _nomba_token_cache['access_token']

        auth_url = f"{self.base_url}/v1/auth/token/issue"
        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
        headers = {
            'Content-Type': 'application/json',
            'accountId': self.account_id,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(auth_url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()

        if data.get('code') != '00':
            message = data.get('message') or 'Unable to issue Nomba token'
            logger.error('Nomba auth request failed with code %s: %s', data.get('code'), message)
            raise NombaAPIError(data.get('code', 'unknown'), message)

        token = data.get('data', {}).get('access_token')
        if not token:
            logger.error('Nomba auth response missing access_token')
            raise NombaAPIError('missing_token', 'Access token missing from Nomba response')

        expires_in = data.get('data', {}).get('expires_in', 1800)
        _nomba_token_cache['access_token'] = token
        _nomba_token_cache['expiry'] = time.time() + expires_in
        return token

    def _run_async(self, coro):
        try:
            return asyncio.run(coro)
        except RuntimeError as exc:
            if 'asyncio.run() cannot be called from a running event loop' in str(exc):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    raise RuntimeError(
                        'Cannot execute NombaClient sync helper from within a running event loop.'
                    ) from exc
            raise

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = await self.get_access_token()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
            'accountId': self.account_id,
        }
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            return response.json()

    def _request_sync(
        self,
        method: str,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._run_async(self._request(method, endpoint, json_body=json_body, params=params))

    def create_checkout_order(self, tenant, amount: str, order_ref: str) -> str:
        """Create a checkout order and return the checkout URL."""
        payload = {
            'order': {
                'amount': str(amount),
                'currency': 'NGN',
                'callbackUrl': f"{settings.SITE_DOMAIN.rstrip('/')}/billing/payment/callback/",
                'customerEmail': tenant.email if getattr(tenant, 'email', None) else tenant.owner.email,
                'customerId': str(tenant.id),
                'orderReference': order_ref,
                'orderMetaData': {'tenantId': str(tenant.id), 'plan': 'monthly'},
            },
            'tokenizeCard': True,
            'allowedPaymentMethods': ['Card']
        }
        logger.info('Creating Nomba checkout order for tenant %s', tenant.id)
        data = self._request_sync('post', '/v1/checkout/order', json_body=payload)

        if data.get('code') != '00':
            message = data.get('message') or 'Checkout order creation failed'
            logger.error('Nomba checkout order failed with code %s: %s', data.get('code'), message)
            raise NombaAPIError(data.get('code', 'unknown'), message)

        checkout_link = data.get('data', {}).get('checkoutLink')
        if not checkout_link:
            logger.error('Nomba checkout order missing checkoutLink')
            raise NombaAPIError('missing_checkout_link', 'Checkout link missing from Nomba response')
        return checkout_link

    def charge_tokenized_card(self, tenant, amount: str, order_ref: str) -> Tuple[bool, Dict[str, Any]]:
        """Charge a previously tokenized card."""
        if not tenant.nomba_token_key:
            raise NombaAPIError('missing_token_key', 'Tenant has no saved Nomba token key')

        payload = {
            'order': {
                'orderReference': order_ref,
                'customerId': str(tenant.id),
                'callbackUrl': f"{settings.SITE_DOMAIN.rstrip('/')}/billing/payment/callback/",
                'customerEmail': tenant.email if getattr(tenant, 'email', None) else tenant.owner.email,
                'amount': str(amount),
                'currency': 'NGN',
                'accountId': self.account_id,
            },
            'tokenKey': tenant.nomba_token_key,
        }
        logger.info('Charging tokenized card for tenant %s', tenant.id)
        data = self._request_sync('post', '/v1/checkout/tokenized-card-payment', json_body=payload)

        success = data.get('code') == '00' and bool(data.get('data', {}).get('status'))
        if not success:
            message = data.get('message') or data.get('data', {}).get('message') or 'Charge failed'
            logger.error('Nomba tokenized card charge failed: %s', message)
            raise NombaAPIError(data.get('code', 'unknown'), message)
        return True, data

    def verify_transaction(self, order_reference: str) -> Tuple[bool, Dict[str, Any]]:
        """Verify a transaction by order reference."""
        logger.info('Verifying Nomba transaction for order %s', order_reference)
        data = self._request_sync(
            'get',
            '/v1/transactions/accounts/single',
            params={'orderReference': order_reference},
        )

        if data.get('code') != '00':
            message = data.get('message') or 'Transaction verification failed'
            logger.error('Nomba verify transaction failed with code %s: %s', data.get('code'), message)
            raise NombaAPIError(data.get('code', 'unknown'), message)

        transaction_data = data.get('data', {}) or {}
        verified = transaction_data.get('status') == 'SUCCESS'
        return verified, transaction_data


NombaService = NombaClient
