from setuptools import find_packages
from setuptools import setup
import os
import re


HERE = os.path.abspath(os.path.dirname(__file__))


README_PATH = os.path.join(HERE, 'README.md')
try:
    with open(README_PATH) as fd:
        README = fd.read()
except IOError:
    README = ''


setup(
    name='exponent_server_sdk',
    version='1.0.0',
    description='Expo Server SDK for Python',
    long_description=README,
    long_description_content_type='text/markdown',
    url='https://github.com/expo/exponent-server-sdk-python',
    author='Expo Team',
    author_email='exponent.team@gmail.com',
    license='MIT',
    install_requires=[
        'requests',
        'six',
    ],
    packages=find_packages(),
    zip_safe=False
)
