"""Provider registry: known names resolve, caching works, unknown names raise clearly."""

import pytest

from roundtable.providers import get_provider, reset_providers
from roundtable.providers.fake import FakeProvider


def test_known_provider_resolves():
    reset_providers()
    provider = get_provider("fake")
    assert isinstance(provider, FakeProvider)


def test_same_name_returns_cached_instance():
    reset_providers()
    first = get_provider("fake")
    second = get_provider("fake")
    assert first is second


def test_unknown_provider_raises_with_known_list():
    reset_providers()
    with pytest.raises(ValueError, match="anthropic"):
        get_provider("not-a-real-provider")


@pytest.mark.asyncio
async def test_fake_provider_returns_completion_with_usage():
    reset_providers()
    provider = get_provider("fake")
    completion = await provider.complete(system="", user="hello", model="fake-model")
    assert completion.text
    assert completion.usage.input_tokens > 0
    assert completion.usage.output_tokens > 0
