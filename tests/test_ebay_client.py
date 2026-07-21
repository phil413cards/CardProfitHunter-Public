import unittest
from unittest.mock import call, patch

import pandas as pd
import requests

import ebay_client


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self.payload = {} if payload is None else payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class EbayClientTests(unittest.TestCase):
    def setUp(self):
        self.credentials = ebay_client.EbayCredentials(
            "test-client-id",
            "test-client-secret",
            "sandbox",
            "EBAY_US",
        )

    def search_with_response(self, response):
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(ebay_client.requests, "get", return_value=response):
            return ebay_client.search_ebay(self.credentials, "test query")

    def normalize_listing(self, **overrides):
        item = {
            "itemId": "item-1",
            "title": "Test Card",
            "price": {"value": "12.34", "currency": "USD"},
            "seller": {"username": "seller"},
            "image": {"imageUrl": "https://example.com/image.jpg"},
            "shippingOptions": [{"shippingCost": {"value": "0"}}],
            "buyingOptions": ["FIXED_PRICE"],
            "condition": "Ungraded",
            "itemWebUrl": "https://example.com/item-1",
        }
        item.update(overrides)
        return ebay_client.normalize_ebay_items([item]).iloc[0]

    def test_timeout_failure_is_sanitized(self):
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=requests.Timeout("sensitive timeout detail"),
        ):
            with self.assertRaisesRegex(ebay_client.EbayApiError, "timed out") as ctx:
                ebay_client.search_ebay(self.credentials, "test query")

        self.assertNotIn("sensitive", str(ctx.exception))

    def test_connection_failure_is_sanitized(self):
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=requests.ConnectionError("secret connection detail"),
        ):
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "Unable to connect",
            ) as ctx:
                ebay_client.search_ebay(self.credentials, "test query")

        self.assertNotIn("secret", str(ctx.exception))

    def test_request_failure_is_sanitized(self):
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=requests.RequestException("private request detail"),
        ):
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "request failed",
            ) as ctx:
                ebay_client.search_ebay(self.credentials, "test query")

        self.assertNotIn("private", str(ctx.exception))

    def test_oauth_timeout_is_sanitized_without_cache_writes(self):
        with patch.object(
            ebay_client,
            "_read_cached_token",
            return_value=None,
        ), patch.object(
            ebay_client,
            "_write_cached_token",
        ) as cache_write, patch.object(
            ebay_client.requests,
            "post",
            side_effect=requests.Timeout("secret OAuth detail"),
        ):
            with self.assertRaisesRegex(ebay_client.EbayApiError, "timed out") as ctx:
                ebay_client.get_application_token(self.credentials)

        cache_write.assert_not_called()
        self.assertNotIn("secret", str(ctx.exception))

    def test_malformed_json_is_sanitized(self):
        response = FakeResponse(payload=ValueError("raw response body"))
        with self.assertRaisesRegex(
            ebay_client.EbayApiError,
            "malformed JSON",
        ) as ctx:
            self.search_with_response(response)

        self.assertNotIn("raw response body", str(ctx.exception))

    def test_malformed_oauth_payload_is_sanitized(self):
        response = FakeResponse(payload={
            "access_token": "test-token",
            "expires_in": "not-a-number",
        })
        with patch.object(
            ebay_client,
            "_read_cached_token",
            return_value=None,
        ), patch.object(
            ebay_client,
            "_write_cached_token",
        ) as cache_write, patch.object(
            ebay_client.requests,
            "post",
            return_value=response,
        ):
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "malformed response",
            ):
                ebay_client.get_application_token(self.credentials)

        cache_write.assert_not_called()

    def test_api_error_does_not_expose_response_body(self):
        response = FakeResponse(
            status_code=400,
            payload={"errors": [{"message": "private API detail"}]},
            text="private response body with token-value",
        )
        with self.assertRaisesRegex(ebay_client.EbayApiError, "HTTP 400") as ctx:
            self.search_with_response(response)

        message = str(ctx.exception)
        self.assertNotIn("private", message)
        self.assertNotIn("token-value", message)

    def test_401_refreshes_token_once_and_retries_once(self):
        responses = [
            FakeResponse(status_code=401),
            FakeResponse(payload={"itemSummaries": [{"itemId": "1"}]}),
        ]
        authorizations = []

        def fake_get(_url, *, headers, **_kwargs):
            authorizations.append(headers["Authorization"])
            return responses.pop(0)

        with patch.object(
            ebay_client,
            "get_application_token",
            side_effect=["cached-token", "fresh-token"],
        ) as token_get, patch.object(
            ebay_client.requests,
            "get",
            side_effect=fake_get,
        ) as request_get:
            items = ebay_client.search_ebay(self.credentials, "test query")

        self.assertEqual(items, [{"itemId": "1"}])
        self.assertEqual(authorizations, ["Bearer cached-token", "Bearer fresh-token"])
        self.assertEqual(request_get.call_count, 2)
        self.assertEqual(
            token_get.call_args_list,
            [
                call(self.credentials, use_cache=True),
                call(self.credentials, use_cache=False),
            ],
        )

    def test_repeated_401_does_not_refresh_more_than_once(self):
        with patch.object(
            ebay_client,
            "get_application_token",
            side_effect=["cached-token", "fresh-token"],
        ) as token_get, patch.object(
            ebay_client.requests,
            "get",
            side_effect=[FakeResponse(status_code=401), FakeResponse(status_code=401)],
        ) as request_get:
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "authentication was rejected",
            ):
                ebay_client.search_ebay(self.credentials, "test query")

        self.assertEqual(token_get.call_count, 2)
        self.assertEqual(request_get.call_count, 2)

    def test_429_honors_retry_after(self):
        responses = [
            FakeResponse(status_code=429, headers={"Retry-After": "2"}),
            FakeResponse(payload={"itemSummaries": []}),
        ]
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=responses,
        ) as request_get, patch.object(ebay_client.time, "sleep") as sleep:
            items = ebay_client.search_ebay(self.credentials, "test query")

        self.assertEqual(items, [])
        self.assertEqual(request_get.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_429_honors_http_date_retry_after_with_cap(self):
        responses = [
            FakeResponse(
                status_code=429,
                headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
            ),
            FakeResponse(payload={"itemSummaries": []}),
        ]
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=responses,
        ), patch.object(ebay_client.time, "sleep") as sleep:
            items = ebay_client.search_ebay(self.credentials, "test query")

        self.assertEqual(items, [])
        sleep.assert_called_once_with(ebay_client.MAX_RETRY_DELAY_SECONDS)

    def test_5xx_retries_are_bounded(self):
        responses = [
            FakeResponse(status_code=503),
            FakeResponse(status_code=502),
            FakeResponse(status_code=500, text="private backend detail"),
        ]
        with patch.object(
            ebay_client,
            "get_application_token",
            return_value="test-token",
        ), patch.object(
            ebay_client.requests,
            "get",
            side_effect=responses,
        ) as request_get, patch.object(ebay_client.time, "sleep") as sleep:
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "temporarily unavailable after retries",
            ) as ctx:
                ebay_client.search_ebay(self.credentials, "test query")

        self.assertEqual(request_get.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1.0), call(2.0)])
        self.assertNotIn("private backend detail", str(ctx.exception))

    def test_invalid_environment_fails_closed_before_requests(self):
        credentials = ebay_client.EbayCredentials(
            "test-client-id",
            "test-client-secret",
            "invalid-environment",
        )
        with patch.object(
            ebay_client,
            "get_application_token",
        ) as token_get, patch.object(ebay_client.requests, "get") as request_get:
            with self.assertRaisesRegex(
                ebay_client.EbayApiError,
                "Invalid eBay environment",
            ):
                ebay_client.search_ebay(credentials, "test query")

        token_get.assert_not_called()
        request_get.assert_not_called()

    def test_empty_null_and_missing_item_summaries_are_valid(self):
        cases = [
            ("empty", {"itemSummaries": []}),
            ("null", {"itemSummaries": None}),
            ("missing", {}),
        ]
        for name, payload in cases:
            with self.subTest(name=name):
                items = self.search_with_response(FakeResponse(payload=payload))
                frame = ebay_client.normalize_ebay_items(items)

                self.assertEqual(items, [])
                self.assertTrue(frame.empty)
                self.assertEqual(
                    tuple(frame.columns),
                    ebay_client.NORMALIZED_EBAY_COLUMNS,
                )

    def test_malformed_item_summaries_are_rejected(self):
        cases = [
            ("mapping", {"itemSummaries": {"itemId": "1"}}),
            ("invalid list member", {"itemSummaries": [None]}),
        ]
        for name, payload in cases:
            with self.subTest(name=name):
                response = FakeResponse(
                    payload=payload,
                    text="private response body with test-client-secret and token-value",
                )
                with self.assertRaisesRegex(
                    ebay_client.EbayApiError,
                    "malformed item summaries",
                ) as ctx:
                    self.search_with_response(response)

                message = str(ctx.exception)
                self.assertNotIn("private response body", message)
                self.assertNotIn("test-client-secret", message)
                self.assertNotIn("token-value", message)
                self.assertNotIn("Traceback", message)

    def test_malformed_nested_listing_fields_normalize_safely(self):
        cases = [
            ("price list", {"price": []}, {"price": None, "currency": ""}),
            ("price string", {"price": "12.34"}, {"price": None, "currency": ""}),
            ("price value list", {"price": {"value": [], "currency": "USD"}}, {"price": None}),
            ("price value text", {"price": {"value": "abc", "currency": "USD"}}, {"price": None}),
            ("price currency list", {"price": {"value": "12.34", "currency": []}}, {"currency": ""}),
            ("current bid list", {"currentBidPrice": []}, {"title": "Test Card"}),
            ("seller list", {"seller": []}, {"seller_username": ""}),
            ("seller username list", {"seller": {"username": []}}, {"seller_username": ""}),
            ("image list", {"image": []}, {"image_url": ""}),
            ("image URL list", {"image": {"imageUrl": []}}, {"image_url": ""}),
            ("shipping mapping", {"shippingOptions": {}}, {"shipping": None}),
            ("shipping string", {"shippingOptions": "free"}, {"shipping": None}),
            ("shipping cost list", {"shippingOptions": [{"shippingCost": []}]}, {"shipping": None}),
            ("shipping value list", {"shippingOptions": [{"shippingCost": {"value": []}}]}, {"shipping": None}),
            ("shipping value text", {"shippingOptions": [{"shippingCost": {"value": "abc"}}]}, {"shipping": None}),
            ("buying options mapping", {"buyingOptions": {}}, {"buying_options": ""}),
            ("buying options numeric", {"buyingOptions": [123]}, {"buying_options": ""}),
            ("title list", {"title": []}, {"title": ""}),
            ("condition list", {"condition": []}, {"condition": ""}),
            ("item ID list", {"itemId": []}, {"item_id": ""}),
            ("item URL list", {"itemWebUrl": []}, {"item_url": ""}),
            ("item location list", {"itemLocation": []}, {"title": "Test Card"}),
        ]

        for name, overrides, expected in cases:
            with self.subTest(name=name):
                row = self.normalize_listing(**overrides)

                for field, value in expected.items():
                    if value is None:
                        self.assertTrue(pd.isna(row[field]), field)
                    else:
                        self.assertEqual(row[field], value, field)

    def test_shipping_zero_and_unknown_values_remain_distinct(self):
        free_shipping = self.normalize_listing(
            shippingOptions=[{"shippingCost": {"value": "0"}}],
        )
        unknown_shipping = self.normalize_listing(shippingOptions=[])

        self.assertEqual(free_shipping["shipping"], 0.0)
        self.assertTrue(pd.isna(unknown_shipping["shipping"]))

    def test_empty_normalization_has_stable_schema(self):
        frame = ebay_client.normalize_ebay_items([])

        self.assertTrue(frame.empty)
        self.assertEqual(
            tuple(frame.columns),
            ebay_client.NORMALIZED_EBAY_COLUMNS,
        )


if __name__ == "__main__":
    unittest.main()
