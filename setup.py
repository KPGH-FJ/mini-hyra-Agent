from setuptools import find_packages, setup

setup(
    name="hyra",
    version="0.1.0",
    description="Clean-room reimplementation of the Hyra research-agent harness",
    packages=find_packages(include=["hyra", "hyra.*"]),
    python_requires=">=3.10",
    entry_points={"console_scripts": ["hyra = hyra.cli:main"]},
)
