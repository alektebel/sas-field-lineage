from setuptools import setup, find_packages

setup(
    name="sas-field-lineage",
    version="0.1.0",
    description="Track field-level data lineage in SAS code",
    author="SAS Lineage Team",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "antlr4-python3-runtime>=4.13.1",
        "streamlit>=1.29.0",
        "pandas>=2.1.4",
        "openpyxl>=3.1.2",
        "graphviz>=0.20.1",
        "networkx>=3.2.1",
    ],
    entry_points={
        "console_scripts": [
            "sas-lineage=sas_lineage.cli:main",
        ],
    },
)
