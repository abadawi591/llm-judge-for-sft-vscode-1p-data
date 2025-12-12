"""
Azure OpenAI Client Module
==========================

Factory functions for creating authenticated Azure OpenAI async clients.

This module provides:
    - Azure Key Vault integration for secure API key retrieval
    - Environment variable fallback for local development
    - Async client creation with proper configuration

Authentication Flow:
    1. Attempt to retrieve API key from Azure Key Vault (production)
    2. Fall back to AZURE_OPENAI_API_KEY environment variable (development)
    3. Raise clear error if neither is available

Key Vault Configuration:
    - Vault Name: abadawikeys
    - Secret Name: gpt-5-2-api-key
    - Subscription: Athena (accessible via az login)

Environment Variables:
    AZURE_OPENAI_API_KEY      : API key (fallback if Key Vault unavailable)
    AZURE_OPENAI_ENDPOINT     : Endpoint URL (optional, uses default)
    AZURE_OPENAI_API_VERSION  : API version (optional, uses default)
"""

import os
from typing import Optional

from openai import AsyncAzureOpenAI

from .config import (
    DEFAULT_API_VERSION,
    KEYVAULT_NAME,
    KEYVAULT_SECRET_NAME,
    AZURE_OPENAI_ENDPOINT,
)


def get_api_key_from_keyvault(
    vault_name: str = KEYVAULT_NAME,
    secret_name: str = KEYVAULT_SECRET_NAME,
) -> str:
    """
    Retrieve the Azure OpenAI API key from Azure Key Vault.
    
    This function uses DefaultAzureCredential for authentication, which
    supports multiple authentication methods in order of priority:
        1. Environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
        2. Managed Identity (in Azure environments)
        3. Azure CLI (az login)
        4. Visual Studio Code
        5. Azure PowerShell
    
    Args:
        vault_name: Name of the Azure Key Vault (default: abadawikeys)
        secret_name: Name of the secret containing the API key (default: gpt-5-2-api-key)
    
    Returns:
        str: The API key retrieved from Key Vault
    
    Raises:
        ImportError: If azure-identity or azure-keyvault-secrets is not installed
        azure.core.exceptions.ClientAuthenticationError: If authentication fails
        azure.core.exceptions.ResourceNotFoundError: If secret doesn't exist
    
    Example:
        >>> api_key = get_api_key_from_keyvault()
        >>> print(f"Retrieved key: {api_key[:8]}...")
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as e:
        raise ImportError(
            "Azure Key Vault dependencies not installed. "
            "Install with: pip install azure-identity azure-keyvault-secrets"
        ) from e
    
    # Construct the Key Vault URL
    vault_url = f"https://{vault_name}.vault.azure.net"
    
    # Create credential and secret client
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    
    # Retrieve the secret
    secret = client.get_secret(secret_name)
    
    return secret.value


def get_azure_openai_client(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    use_keyvault: bool = True,
) -> AsyncAzureOpenAI:
    """
    Create and return an AsyncAzureOpenAI client for Azure OpenAI API calls.
    
    This factory function handles authentication by:
        1. Using explicitly provided api_key if given
        2. Attempting Key Vault retrieval if use_keyvault=True
        3. Falling back to AZURE_OPENAI_API_KEY environment variable
    
    Args:
        api_key: Explicit API key (optional, overrides all other methods)
        endpoint: Azure OpenAI endpoint URL (optional, uses env var or default)
        api_version: API version string (optional, uses env var or default)
        use_keyvault: Whether to attempt Key Vault retrieval (default: True)
    
    Returns:
        AsyncAzureOpenAI: Configured async client ready for API calls
    
    Raises:
        ValueError: If no API key is available from any source
        ImportError: If Key Vault dependencies are missing and use_keyvault=True
    
    Example:
        >>> client = get_azure_openai_client()
        >>> response = await client.chat.completions.create(
        ...     model="gpt-5.2",
        ...     messages=[{"role": "user", "content": "Hello!"}]
        ... )
    
    Note:
        The returned client is async and must be used with await:
        
        >>> async def main():
        ...     client = get_azure_openai_client()
        ...     resp = await client.chat.completions.create(...)
    """
    # Resolve API key
    resolved_api_key = api_key
    
    if resolved_api_key is None:
        # Try Key Vault first (production)
        if use_keyvault:
            try:
                resolved_api_key = get_api_key_from_keyvault()
                print("✓ API key retrieved from Azure Key Vault")
            except Exception as e:
                print(f"⚠ Key Vault retrieval failed: {e}")
                print("  Falling back to environment variable...")
        
        # Fall back to environment variable
        if resolved_api_key is None:
            resolved_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    
    if not resolved_api_key:
        raise ValueError(
            "No Azure OpenAI API key available. Provide one via:\n"
            "  1. api_key parameter\n"
            "  2. Azure Key Vault (vault: abadawikeys, secret: gpt-5-2-api-key)\n"
            "  3. AZURE_OPENAI_API_KEY environment variable"
        )
    
    # Resolve endpoint
    resolved_endpoint = (
        endpoint
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or AZURE_OPENAI_ENDPOINT
    )
    
    # Resolve API version
    resolved_api_version = (
        api_version
        or os.environ.get("AZURE_OPENAI_API_VERSION")
        or DEFAULT_API_VERSION
    )
    
    # Create and return the async client
    client = AsyncAzureOpenAI(
        api_key=resolved_api_key,
        azure_endpoint=resolved_endpoint,
        api_version=resolved_api_version,
    )
    
    return client

