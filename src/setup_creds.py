"""
One-time script to derive CLOB API credentials from private key.
Run this once, then copy the output to your .env file.
"""
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

def main():
    load_dotenv()

    pk = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    if not pk:
        print("Set POLYMARKET_PRIVATE_KEY in .env first")
        return

    if not pk.startswith("0x"):
        pk = "0x" + pk

    print("Deriving API credentials from private key...")

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=137
    )

    creds = client.create_or_derive_api_creds()

    print("\n" + "=" * 50)
    print("API Credentials Derived Successfully")
    print("=" * 50)
    print(f"API Key:     {creds.api_key}")
    print(f"Secret:      {creds.api_secret}")
    print(f"Passphrase:  {creds.api_passphrase}")
    print("=" * 50)
    print("\nThe bot will auto-derive these on startup.")

if __name__ == "__main__":
    main()
