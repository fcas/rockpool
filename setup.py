import logging
from distutils.core import setup
import setuptools
from setuptools import Extension

# - Read version
exec(open("rockpool/version.py").read())

setup_args = {
    "name": "rockpool",
    "author": "SynSense",
    "author_email": "dylan.muir@synsense.ai",
    "version": __version__,
    "packages": setuptools.find_packages(),
    "install_requires": ["numpy", "scipy"],
    "extras_require": {
        "all": [
            "tqdm",
            "brian2",
            "pytest>=6.0",
            "pytest-xdist",
            "torch",
            "torchvision",
            "jax>=0.2.13",
            "jaxlib>=0.1.66",
            "sphinx",
            "nbsphinx",
            "sphinx-autobuild",
            "sphinx-rtd-theme",
            "recommonmark",
            "pandoc",
            "xylosim",
            "samna>=0.10.32.0",
        ]
    },
    "description": "A Python package for developing, simulating and training spiking neural networks, and deploying on neuromorphic hardware",
    "long_description": open("README.md").read(),
    "long_description_content_type": "text/markdown",
    "classifiers": [
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
    ],
    "keywords": "spiking neural network SNN neuromorphic",
    "python_requires": ">=3.6",
    "project_urls": {
        "Source Code": "https://github.com/SynSense/rockpool",
        "Documentation": "https://rockpool.ai",
        "Bug Tracker": "https://github.com/SynSense/rockpool/issues",
    },
    "include_package_data": True,
}

setup(**setup_args)
