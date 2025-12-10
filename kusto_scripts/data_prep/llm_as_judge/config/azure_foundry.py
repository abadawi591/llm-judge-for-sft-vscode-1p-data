"""
Azure Foundry Client Configuration for Claude Sonnet 4.5

This module handles authentication and client setup for the Claude Sonnet 4.5
model deployed on Azure Foundry (Azure AI Services). Supports both sync and
async clients with tenacity retry logic.

Configuration:
    - Endpoint: https://pagolnar-5985-resource.services.ai.azure.com/anthropic/
    - Model: claude-sonnet-4-5
    - Key Vault: claude-keyvault
    - Secret Name: claude-sonnet-4-5-azurefoundary

Usage:
    # Synchronous
    from config.azure_foundry import get_anthropic_client
    client = get_anthropic_client()
    
    # Asynchronous
    from config.azure_foundry import get_async_anthropic_client
    async_client = get_async_anthropic_client()
    
    # With retry decorator
    from config.azure_foundry import with_retry, with_async_retry
"""

import os
import logging
from typing import Optional
from anthropic import AnthropicFoundry
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Constants
# =============================================================================

AZURE_FOUNDRY_ENDPOINT = "https://pagolnar-5985-resource.services.ai.azure.com/anthropic/"
MODEL_NAME = "claude-sonnet-4-5"
KEY_VAULT_URL = "https://claude-keyvault.vault.azure.net/"
SECRET_NAME = "claude-sonnet-4-5-azurefoundary"

# Retry configuration
MAX_RETRIES = 5
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 60


# =============================================================================
# Retry Decorators
# =============================================================================

# Common transient exceptions to retry
RETRYABLE_EXCEPTIONS = (
    Exception,  # Will be refined based on actual Anthropic exceptions
)


def create_retry_decorator(is_async: bool = False):
    """Create a retry decorator with tenacity."""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


# Pre-built decorators
with_retry = create_retry_decorator(is_async=False)
with_async_retry = create_retry_decorator(is_async=True)


# =============================================================================
# API Key Retrieval
# =============================================================================

def get_api_key_from_keyvault() -> str:
    """
    Retrieve the API key from Azure Key Vault.
    
    Returns:
        str: The API key for Claude Sonnet 4.5 on Azure Foundry
        
    Raises:
        Exception: If unable to retrieve the secret from Key Vault
    """
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)
    
    secret = client.get_secret(SECRET_NAME)
    return secret.value


def get_api_key(use_keyvault: bool = True) -> str:
    """
    Get API key either from Key Vault or environment variable.
    
    Args:
        use_keyvault: If True, retrieve from Azure Key Vault. 
                      If False, use ANTHROPIC_API_KEY environment variable.
    
    Returns:
        str: The API key
        
    Raises:
        ValueError: If no API key is found
    """
    if use_keyvault:
        return get_api_key_from_keyvault()
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key found. Set ANTHROPIC_API_KEY environment variable "
            "or use use_keyvault=True to retrieve from Azure Key Vault."
        )
    return api_key


# =============================================================================
# Synchronous Client
# =============================================================================

_sync_client_instance: Optional[AnthropicFoundry] = None


def get_anthropic_client(use_keyvault: bool = True) -> AnthropicFoundry:
    """
    Get or create a singleton Anthropic Foundry client (synchronous).
    
    Args:
        use_keyvault: If True, retrieve API key from Azure Key Vault
        
    Returns:
        AnthropicFoundry: Configured client for Claude Sonnet 4.5
    """
    global _sync_client_instance
    
    if _sync_client_instance is None:
        api_key = get_api_key(use_keyvault=use_keyvault)
        _sync_client_instance = AnthropicFoundry(
            api_key=api_key,
            base_url=AZURE_FOUNDRY_ENDPOINT
        )
        logger.info("Created synchronous Anthropic Foundry client")
    
    return _sync_client_instance


# =============================================================================
# Asynchronous Client
# =============================================================================

# Try to import async client
try:
    from anthropic import AsyncAnthropicFoundry
    ASYNC_AVAILABLE = True
except ImportError:
    # Fallback: create async wrapper if AsyncAnthropicFoundry not available
    ASYNC_AVAILABLE = False
    AsyncAnthropicFoundry = None
    logger.warning("AsyncAnthropicFoundry not available, async features limited")


_async_client_instance = None


def get_async_anthropic_client(use_keyvault: bool = True):
    """
    Get or create a singleton async Anthropic Foundry client.
    
    Args:
        use_keyvault: If True, retrieve API key from Azure Key Vault
        
    Returns:
        AsyncAnthropicFoundry: Configured async client for Claude Sonnet 4.5
        
    Raises:
        ImportError: If async client is not available
    """
    global _async_client_instance
    
    if not ASYNC_AVAILABLE:
        raise ImportError(
            "AsyncAnthropicFoundry is not available. "
            "Please upgrade anthropic package: pip install --upgrade anthropic"
        )
    
    if _async_client_instance is None:
        api_key = get_api_key(use_keyvault=use_keyvault)
        _async_client_instance = AsyncAnthropicFoundry(
            api_key=api_key,
            base_url=AZURE_FOUNDRY_ENDPOINT
        )
        logger.info("Created asynchronous Anthropic Foundry client")
    
    return _async_client_instance


def create_async_client(api_key: Optional[str] = None):
    """
    Create a new async Anthropic Foundry client (non-singleton).
    
    Args:
        api_key: API key to use. If None, retrieves from Key Vault.
        
    Returns:
        AsyncAnthropicFoundry: New async client instance
    """
    if not ASYNC_AVAILABLE:
        raise ImportError("AsyncAnthropicFoundry is not available")
    
    if api_key is None:
        api_key = get_api_key_from_keyvault()
    
    return AsyncAnthropicFoundry(
        api_key=api_key,
        base_url=AZURE_FOUNDRY_ENDPOINT
    )


# =============================================================================
# Model Constants
# =============================================================================

def get_model_name() -> str:
    """Get the model deployment name."""
    return MODEL_NAME


def get_endpoint() -> str:
    """Get the Azure Foundry endpoint."""
    return AZURE_FOUNDRY_ENDPOINT


# =============================================================================
# Testing
# =============================================================================

def test_connection() -> bool:
    """Test the synchronous connection to Azure Foundry."""
    try:
        client = get_anthropic_client()
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'ok'"}]
        )
        return len(response.content) > 0
    except Exception as e:
        logger.error(f"Sync connection test failed: {e}")
        return False


async def test_async_connection() -> bool:
    """Test the asynchronous connection to Azure Foundry."""
    try:
        client = get_async_anthropic_client()
        response = await client.messages.create(
            model=MODEL_NAME,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'ok'"}]
        )
        return len(response.content) > 0
    except Exception as e:
        logger.error(f"Async connection test failed: {e}")
        return False


if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Azure Foundry connection...")
    
    # Test sync
    print("\n1. Testing synchronous client...")
    if test_connection():
        print("   ✅ Sync connection successful!")
    else:
        print("   ❌ Sync connection failed!")
    
    # Test async
    print("\n2. Testing asynchronous client...")
    if ASYNC_AVAILABLE:
        if asyncio.run(test_async_connection()):
            print("   ✅ Async connection successful!")
        else:
            print("   ❌ Async connection failed!")
    else:
        print("   ⚠️ Async client not available")
