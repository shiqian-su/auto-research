from setuptools import find_packages, setup


setup(
    name="auto-research",
    version="0.1.0",
    description="A small Codex-based auto-research framework with resumable sessions.",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "auto-research=auto_research.cli:main",
        ]
    },
)
