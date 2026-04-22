from setuptools import setup, find_packages

setup(
    name="polymarket-btc-bot",
    version="1.0.0",
    description="Automated BTC Up/Down 5-Minute Trading Bot for Polymarket",
    author="Your Name",
    packages=find_packages(),
    install_requires=[
        "py-clob-client>=0.34.0",
        "requests>=2.31.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "yfinance>=0.2.28",
        "web3>=6.0.0",
        "eth-abi>=4.0.0",
        "eth-utils>=2.0.0",
        "python-dotenv>=1.0.0",
        "colorama>=0.4.6",
        "rich>=13.0.0",
    ],
    dependency_links=[
        "git+https://github.com/Polymarket/py-builder-relayer-client.git",
        "git+https://github.com/Polymarket/py-builder-signing-sdk.git",
    ],
    python_requires=">=3.10",
)
